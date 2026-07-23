from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from contextlib import suppress
from dataclasses import asdict, dataclass
from uuid import UUID

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

router = Router()

# A local gpt-oss server normally handles one expensive generation efficiently at a time.
CHAT_REQUEST_LOCK = asyncio.Lock()

TELEGRAM_TEXT_LIMIT = 4096
SAFE_TEXT_CHUNK_SIZE = 3900
DOCUMENTS_PAGE_SIZE = 8
_INDEXING_POLL_INTERVAL_SECONDS = 3
_INDEXING_POLL_TIMEOUT_SECONDS = 180
_DUPLICATE_DOCUMENT_ID = re.compile(
    r"document id\s+([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


@dataclass(frozen=True, slots=True)
class ActiveDocument:
    document_id: str
    filename: str


# Redis is the normal storage. The in-memory dict is only a safe fallback if Redis is down.
ACTIVE_DOCUMENTS: dict[int, ActiveDocument] = {}
active_document_redis: Redis | None = None


def _active_document_key(user_id: int) -> str:
    return f"telegram:active_document:{user_id}"


async def _get_active_document(user_id: int) -> ActiveDocument | None:
    if active_document_redis is not None:
        try:
            raw = await active_document_redis.get(_active_document_key(user_id))
            if raw:
                payload = json.loads(raw)
                return ActiveDocument(
                    document_id=str(payload["document_id"]),
                    filename=str(payload["filename"]),
                )
        except (RedisError, ValueError, KeyError, TypeError):
            logger.exception("Could not read active Telegram document from Redis")
    return ACTIVE_DOCUMENTS.get(user_id)


async def _set_active_document(user_id: int, active: ActiveDocument) -> None:
    ACTIVE_DOCUMENTS[user_id] = active
    if active_document_redis is not None:
        try:
            await active_document_redis.set(
                _active_document_key(user_id),
                json.dumps(asdict(active), ensure_ascii=False, separators=(",", ":")),
            )
        except RedisError:
            logger.exception("Could not save active Telegram document to Redis")


async def _clear_active_document(user_id: int) -> None:
    ACTIVE_DOCUMENTS.pop(user_id, None)
    if active_document_redis is not None:
        try:
            await active_document_redis.delete(_active_document_key(user_id))
        except RedisError:
            logger.exception("Could not clear active Telegram document in Redis")


def _user_is_allowed(user_id: int | None) -> bool:
    return user_id is not None and user_id in settings.allowed_telegram_users


def _is_allowed(message: Message) -> bool:
    user = message.from_user
    return _user_is_allowed(user.id if user is not None else None)


def _callback_is_allowed(callback: CallbackQuery) -> bool:
    return _user_is_allowed(callback.from_user.id)


def _headers() -> dict[str, str]:
    return {"X-API-Key": settings.backend_api_key}


async def _deny(message: Message) -> None:
    await message.answer("Access denied.")


async def _safe_edit(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Edit a bot message without crashing on harmless Telegram errors."""
    try:
        await message.edit_text(
            text[:TELEGRAM_TEXT_LIMIT],
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Could not edit Telegram message: %s", exc)


async def _fetch_documents() -> list[dict[str, object]]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{settings.backend_url.rstrip('/')}/api/v1/documents",
            headers=_headers(),
        )
        response.raise_for_status()
        payload = response.json()

    items = payload.get("items", [])
    if not isinstance(items, list):
        raise ValueError("Backend returned an invalid document list")
    return [item for item in items if isinstance(item, dict)]


async def _fetch_document(document_id: str) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{settings.backend_url.rstrip('/')}/api/v1/documents/{document_id}",
            headers=_headers(),
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Backend returned an invalid document payload")
    return payload


def _short_filename(filename: str, limit: int = 46) -> str:
    clean = filename.replace("\n", " ").replace("\r", " ").strip()
    if len(clean) <= limit:
        return clean
    return f"{clean[: limit - 1]}…"


async def _documents_view(
    documents: list[dict[str, object]],
    user_id: int,
    requested_page: int,
) -> tuple[str, InlineKeyboardMarkup | None]:
    ready = [document for document in documents if document.get("status") == "ready"]
    processing_count = sum(1 for document in documents if document.get("status") == "processing")
    failed_count = sum(1 for document in documents if document.get("status") == "failed")

    active = await _get_active_document(user_id)
    ready_ids = {str(document.get("id", "")) for document in ready}
    if active is not None and active.document_id not in ready_ids:
        await _clear_active_document(user_id)
        active = None

    if not ready:
        extra = []
        if processing_count:
            extra.append(f"⏳ Обробляється: {processing_count}")
        if failed_count:
            extra.append(f"❌ Помилок індексації: {failed_count}")
        suffix = "\n" + "\n".join(extra) if extra else ""
        return (
            "У базі ще немає готових документів. Надішли PDF, DOCX або TXT боту." + suffix,
            None,
        )

    page_count = max(1, math.ceil(len(ready) / DOCUMENTS_PAGE_SIZE))
    page = min(max(requested_page, 0), page_count - 1)
    start = page * DOCUMENTS_PAGE_SIZE
    page_documents = ready[start : start + DOCUMENTS_PAGE_SIZE]

    rows: list[list[InlineKeyboardButton]] = []
    for document in page_documents:
        document_id = str(document.get("id", ""))
        filename = str(document.get("filename", "document"))
        selected = active is not None and active.document_id == document_id
        prefix = "✅" if selected else "📄"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix} {_short_filename(filename)}",
                    callback_data=f"select_doc:{document_id}",
                )
            ]
        )

    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="⬅️", callback_data=f"docs_page:{page - 1}"))
    navigation.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{page_count}",
            callback_data=f"docs_page:{page}",
        )
    )
    if page + 1 < page_count:
        navigation.append(InlineKeyboardButton(text="➡️", callback_data=f"docs_page:{page + 1}"))
    rows.append(navigation)
    rows.append(
        [
            InlineKeyboardButton(
                text="🌐 Шукати по всіх документах",
                callback_data="scope_all",
            )
        ]
    )

    current = (
        f"📄 Активний документ: {active.filename}"
        if active is not None
        else "🌐 Поточний режим: пошук по всіх документах"
    )
    status_line = ""
    if processing_count or failed_count:
        status_line = f"\n\nСтатус: готових {len(ready)}, обробляється {processing_count}, помилок {failed_count}."
    text = f"{current}\n\nОберіть документ, у межах якого бот має шукати відповіді.{status_line}"
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_documents(message: Message, page: int = 0) -> None:
    user = message.from_user
    if user is None:
        return
    try:
        documents = await _fetch_documents()
        text, keyboard = await _documents_view(documents, user.id, page)
    except (httpx.HTTPError, ValueError):
        logger.exception("Could not fetch document list")
        await message.answer("❌ Не вдалося отримати список документів.")
        return
    await message.answer(text, reply_markup=keyboard)


async def _show_chat_progress(
    status_message: Message,
    bot: Bot,
    scope_text: str,
) -> None:
    """Keep one Telegram message updated while the local LLM is processing."""
    stages = (
        (5, f"🔎 Шукаю релевантні фрагменти…\n{scope_text}"),
        (15, f"🧠 Формую відповідь за знайденими джерелами…\n{scope_text}"),
        (30, f"⏳ Локальна модель ще працює…\n{scope_text}"),
    )

    elapsed = 0
    for delay_seconds, text in stages:
        await asyncio.sleep(delay_seconds)
        elapsed += delay_seconds
        await bot.send_chat_action(
            chat_id=status_message.chat.id,
            action=ChatAction.TYPING,
        )
        await _safe_edit(status_message, text)

    while True:
        await asyncio.sleep(30)
        elapsed += 30
        await bot.send_chat_action(
            chat_id=status_message.chat.id,
            action=ChatAction.TYPING,
        )
        minutes, seconds = divmod(elapsed, 60)
        await _safe_edit(
            status_message,
            f"⏳ Модель ще працює… Минуло {minutes}:{seconds:02d}.\n{scope_text}",
        )


async def _finish_progress(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def _build_answer(payload: dict[str, object]) -> str:
    answer = str(payload.get("answer") or "Не вдалося сформувати відповідь.")
    sources = payload.get("sources", [])

    if not isinstance(sources, list) or not sources:
        return answer

    source_lines: list[str] = []
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            continue
        page_number = source.get("page_number")
        page = f", стор. {page_number}" if page_number else ""
        source_lines.append(f"[S{index}] {source.get('filename', 'document')}{page}")

    if not source_lines:
        return answer
    return f"{answer}\n\nДжерела:\n" + "\n".join(source_lines)


async def _send_result_by_editing_status(
    original_message: Message,
    status_message: Message,
    text: str,
) -> None:
    chunks = [
        text[start_index : start_index + SAFE_TEXT_CHUNK_SIZE]
        for start_index in range(0, len(text), SAFE_TEXT_CHUNK_SIZE)
    ] or ["Не вдалося сформувати відповідь."]

    await _safe_edit(status_message, chunks[0])
    for chunk in chunks[1:]:
        await original_message.answer(chunk)


async def _wait_for_indexing(
    status_message: Message,
    document_id: str,
) -> dict[str, object] | None:
    elapsed = 0
    last_status = "processing"
    while elapsed <= _INDEXING_POLL_TIMEOUT_SECONDS:
        try:
            payload = await _fetch_document(document_id)
        except (httpx.HTTPError, ValueError):
            logger.exception("Could not poll document status")
            return None

        status_value = str(payload.get("status", "unknown"))
        if status_value == "ready":
            return payload
        if status_value == "failed":
            return payload

        if status_value != last_status or elapsed % 15 == 0:
            await _safe_edit(
                status_message,
                "⏳ Документ прийнято. Індексую у worker…\n"
                f"Статус: {status_value}\n"
                f"Минуло: {elapsed} с",
            )
            last_status = status_value
        await asyncio.sleep(_INDEXING_POLL_INTERVAL_SECONDS)
        elapsed += _INDEXING_POLL_INTERVAL_SECONDS
    return None


@router.message(CommandStart())
async def start(message: Message) -> None:
    if not _is_allowed(message):
        await _deny(message)
        return
    await message.answer(
        "Надішли PDF, DOCX або UTF-8 TXT, щоб додати його до бази знань.\n\n"
        "Команди:\n"
        "/documents — вибрати активний документ\n"
        "/current — показати поточний режим пошуку\n"
        "/all — шукати по всіх документах\n"
        "/health — перевірити стан сервісів\n\n"
        "Після вибору документа просто напиши запитання."
    )


@router.message(Command("documents"))
async def documents(message: Message) -> None:
    if not _is_allowed(message):
        await _deny(message)
        return
    await _show_documents(message)


@router.message(Command("current"))
async def current_scope(message: Message) -> None:
    if not _is_allowed(message):
        await _deny(message)
        return
    user = message.from_user
    if user is None:
        return
    active = await _get_active_document(user.id)
    if active is None:
        await message.answer("🌐 Зараз бот шукає по всіх документах.")
    else:
        await message.answer(
            f"📄 Активний документ: {active.filename}\n"
            "Щоб змінити його, використай /documents."
        )


@router.message(Command("all"))
async def use_all_documents(message: Message) -> None:
    if not _is_allowed(message):
        await _deny(message)
        return
    user = message.from_user
    if user is None:
        return
    await _clear_active_document(user.id)
    await message.answer("🌐 Увімкнено пошук по всіх документах.")


@router.message(Command("health"))
async def health(message: Message) -> None:
    if not _is_allowed(message):
        await _deny(message)
        return

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{settings.backend_url.rstrip('/')}/health")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        logger.exception("Backend health check failed")
        await message.answer("❌ API недоступний або повернув некоректну відповідь.")
        return

    await message.answer(
        "✅ Бот працює.\n"
        f"API: {payload.get('status', 'unknown')}\n"
        f"PostgreSQL: {payload.get('database', 'unknown')}\n"
        f"Redis: {payload.get('redis', 'unknown')}"
    )


@router.callback_query(F.data.startswith("docs_page:"))
async def document_page(callback: CallbackQuery) -> None:
    if not _callback_is_allowed(callback):
        await callback.answer("Access denied.", show_alert=True)
        return
    if not isinstance(callback.message, Message) or callback.data is None:
        await callback.answer()
        return

    try:
        page = int(callback.data.split(":", 1)[1])
        documents = await _fetch_documents()
        text, keyboard = await _documents_view(documents, callback.from_user.id, page)
        await _safe_edit(callback.message, text, keyboard)
        await callback.answer()
    except (ValueError, httpx.HTTPError):
        logger.exception("Could not switch document page")
        await callback.answer("Не вдалося оновити список.", show_alert=True)


@router.callback_query(F.data.startswith("select_doc:"))
async def select_document(callback: CallbackQuery) -> None:
    if not _callback_is_allowed(callback):
        await callback.answer("Access denied.", show_alert=True)
        return
    if not isinstance(callback.message, Message) or callback.data is None:
        await callback.answer()
        return

    document_id = callback.data.split(":", 1)[1]
    try:
        UUID(document_id)
        documents = await _fetch_documents()
    except (ValueError, httpx.HTTPError):
        logger.exception("Could not select document")
        await callback.answer("Не вдалося вибрати документ.", show_alert=True)
        return

    selected = next(
        (
            item
            for item in documents
            if str(item.get("id")) == document_id and item.get("status") == "ready"
        ),
        None,
    )
    if selected is None:
        await _clear_active_document(callback.from_user.id)
        await callback.answer("Документ не знайдено або він ще не готовий.", show_alert=True)
        return

    filename = str(selected.get("filename", "document"))
    await _set_active_document(callback.from_user.id, ActiveDocument(document_id, filename))
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📚 Змінити документ", callback_data="docs_page:0")],
            [InlineKeyboardButton(text="🌐 Шукати по всіх", callback_data="scope_all")],
        ]
    )
    await _safe_edit(
        callback.message,
        f"✅ Активний документ: {filename}\n\nТепер надішли запитання.",
        keyboard,
    )
    await callback.answer("Документ вибрано")


@router.callback_query(F.data == "scope_all")
async def select_all_documents(callback: CallbackQuery) -> None:
    if not _callback_is_allowed(callback):
        await callback.answer("Access denied.", show_alert=True)
        return
    await _clear_active_document(callback.from_user.id)
    if isinstance(callback.message, Message):
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📄 Вибрати документ", callback_data="docs_page:0")]
            ]
        )
        await _safe_edit(
            callback.message,
            "🌐 Увімкнено пошук по всіх документах.",
            keyboard,
        )
    await callback.answer("Пошук по всіх документах")


@router.message(F.document)
async def upload_document(message: Message, bot: Bot) -> None:
    if not _is_allowed(message):
        await _deny(message)
        return
    if message.document is None:
        return

    if (message.document.file_size or 0) > settings.max_upload_bytes:
        await message.answer("❌ Файл перевищує дозволений розмір.")
        return

    status_message = await message.answer("⏳ Отримую файл із Telegram…")

    try:
        telegram_file = await bot.get_file(message.document.file_id)
        if telegram_file.file_path is None:
            await _safe_edit(status_message, "❌ Не вдалося отримати файл із Telegram.")
            return

        downloaded = await bot.download_file(telegram_file.file_path)
        if downloaded is None:
            await _safe_edit(status_message, "❌ Не вдалося завантажити файл.")
            return
        data = downloaded.read()
    except Exception:
        logger.exception("Telegram file download failed")
        await _safe_edit(status_message, "❌ Помилка під час завантаження файлу з Telegram.")
        return

    await _safe_edit(status_message, "⏳ Файл отримано. Передаю документ у чергу індексації…")
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)

    files = {
        "file": (
            message.document.file_name or "document",
            data,
            message.document.mime_type or "application/octet-stream",
        )
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.backend_url.rstrip('/')}/api/v1/documents",
                headers=_headers(),
                files=files,
            )
    except httpx.TimeoutException:
        logger.exception("Backend upload request timed out")
        await _safe_edit(
            status_message,
            "⌛ Сервіс не встиг прийняти документ. Спробуй ще раз пізніше.",
        )
        return
    except httpx.HTTPError:
        logger.exception("Backend upload request failed")
        await _safe_edit(status_message, "❌ Сервіс тимчасово недоступний.")
        return

    user = message.from_user
    if response.status_code == 201:
        payload = response.json()
        document_id = str(payload["id"])
        status_value = str(payload.get("status", "processing"))
        ready_payload = payload if status_value == "ready" else await _wait_for_indexing(status_message, document_id)

        if ready_payload is None:
            await _safe_edit(
                status_message,
                "⏳ Документ прийнято, але ще обробляється. Перевір готовність через /documents.",
            )
            return
        if str(ready_payload.get("status")) == "failed":
            detail = str(ready_payload.get("error_message") or "Indexing failed")
            await _safe_edit(status_message, f"❌ Індексація не вдалася: {detail}")
            return

        if user is not None:
            await _set_active_document(
                user.id,
                ActiveDocument(
                    document_id=str(ready_payload["id"]),
                    filename=str(ready_payload["filename"]),
                ),
            )
        await _safe_edit(
            status_message,
            "✅ Документ додано й вибрано як активний: "
            f"{ready_payload['filename']}\nФрагментів: {ready_payload['chunk_count']}",
        )
        return

    try:
        detail = str(response.json().get("detail", "Upload failed"))
    except ValueError:
        detail = "Upload failed"

    if response.status_code == 409:
        match = _DUPLICATE_DOCUMENT_ID.search(detail)
        if match is not None and user is not None:
            document_id = match.group(1)
            try:
                payload = await _fetch_document(document_id)
            except (httpx.HTTPError, ValueError):
                payload = {"id": document_id, "filename": message.document.file_name or "document"}

            if payload.get("status") == "ready":
                await _set_active_document(
                    user.id,
                    ActiveDocument(
                        document_id=document_id,
                        filename=str(payload.get("filename") or message.document.file_name or "document"),
                    ),
                )
                await _safe_edit(
                    status_message,
                    "ℹ️ Цей документ уже був доданий і тепер вибраний як активний.",
                )
            else:
                await _safe_edit(
                    status_message,
                    f"ℹ️ Цей документ уже додано, але його статус: {payload.get('status', 'unknown')}.",
                )
        else:
            await _safe_edit(status_message, f"ℹ️ Цей документ уже додано.\n{detail}")
    elif response.status_code in {400, 413, 415, 422}:
        await _safe_edit(status_message, f"❌ Документ не прийнято: {detail}")
    else:
        await _safe_edit(status_message, f"❌ Не вдалося додати документ: {detail}")


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    if not _is_allowed(message):
        await _deny(message)
        return
    await message.answer("Невідома команда. Використай /start для списку команд.")


@router.message(F.text & ~F.text.startswith("/"))
async def ask_question(message: Message, bot: Bot) -> None:
    if not _is_allowed(message):
        await _deny(message)
        return
    if not message.text:
        return
    user = message.from_user
    if user is None:
        return
    active = await _get_active_document(user.id)
    scope_text = (
        f"📄 Документ: {active.filename}"
        if active is not None
        else "🌐 Пошук по всіх документах"
    )
    status_message = await message.answer(f"⏳ Обробляю запит…\n{scope_text}")

    if CHAT_REQUEST_LOCK.locked():
        await _safe_edit(
            status_message,
            f"⏳ Інший запит уже обробляється. Твій запит у черзі…\n{scope_text}",
        )

    async with CHAT_REQUEST_LOCK:
        progress_task = asyncio.create_task(_show_chat_progress(status_message, bot, scope_text))
        request_payload: dict[str, str] = {"question": message.text}
        if active is not None:
            request_payload["document_id"] = active.document_id

        read_timeout_seconds = max(settings.llm_timeout_seconds + 60.0, 600.0)
        timeout = httpx.Timeout(
            connect=10.0,
            read=read_timeout_seconds,
            write=60.0,
            pool=read_timeout_seconds,
        )

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{settings.backend_url.rstrip('/')}/api/v1/chat",
                    headers=_headers(),
                    json=request_payload,
                )
        except httpx.TimeoutException:
            logger.exception("Backend chat request timed out after %.0f seconds", read_timeout_seconds)
            await _finish_progress(progress_task)
            await _safe_edit(
                status_message,
                "⌛ Модель не завершила відповідь у межах таймауту. "
                "Перевір локальний LLM-сервер і повтори запит.",
            )
            return
        except httpx.HTTPError:
            logger.exception("Backend chat request failed")
            await _finish_progress(progress_task)
            await _safe_edit(status_message, "❌ Сервіс тимчасово недоступний.")
            return

        await _finish_progress(progress_task)

        if response.status_code != 200:
            try:
                detail = str(response.json().get("detail", "Request failed"))
            except ValueError:
                detail = "Request failed"

            if response.status_code in {404, 409} and active is not None:
                await _clear_active_document(user.id)
                await _safe_edit(
                    status_message,
                    "❌ Активний документ не готовий або більше не існує. "
                    "Режим скинуто на всі документи; вибери інший через /documents.",
                )
                return

            await _safe_edit(status_message, f"❌ Помилка: {detail}")
            return

        try:
            payload = response.json()
        except ValueError:
            logger.exception("Backend returned invalid JSON")
            await _safe_edit(status_message, "❌ Сервіс повернув некоректну відповідь.")
            return

        answer = _build_answer(payload)
        await _send_result_by_editing_status(message, status_message, answer)


async def main() -> None:
    global active_document_redis
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    if not settings.allowed_telegram_users:
        raise RuntimeError("ALLOWED_TELEGRAM_USER_IDS is empty; refusing to start an open bot")

    bot = Bot(token=settings.telegram_bot_token)
    active_document_redis = Redis.from_url(settings.redis_url, decode_responses=True)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)

    bot_info = await bot.get_me()
    logger.info(
        "Telegram bot started: @%s (id=%s); allowed users=%s; backend=%s",
        bot_info.username,
        bot_info.id,
        sorted(settings.allowed_telegram_users),
        settings.backend_url,
    )

    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()
        if active_document_redis is not None:
            await active_document_redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
