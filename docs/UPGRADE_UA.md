# Що змінено в цій версії

## Production-доробки

- Індексацію документів винесено з HTTP request у Redis-backed worker.
- `POST /api/v1/documents` тепер швидко створює документ зі статусом `processing` і кладе задачу в чергу.
- Додано `GET /api/v1/documents/{document_id}` для перевірки статусу `processing`, `ready` або `failed`.
- Worker читає тимчасові raw bytes із Redis, витягує текст, робить chunks, embeddings і записує chunks у PostgreSQL.
- Додано hybrid retrieval: vector search + PostgreSQL full-text rank.
- DOCX extraction тепер бере не тільки paragraphs, а й таблиці.
- Telegram bot зберігає активний документ у Redis, тому вибір не зникає після рестарту бота.
- Telegram bot після upload чекає готовності документа й автоматично вибирає його активним, коли worker завершив індексацію.
- Додано базовий `eval/run_eval.py` для перевірки latency, source hit rate, citations і expected terms.

## Важливо

`.env` навмисно не включено в архів. Створи його через:

```powershell
python scripts/init_env.py
```

Або перенеси свої локальні значення з попереднього `.env`, але не пуш його в GitHub.

## Запуск

```powershell
docker compose up --build -d
```

Для Telegram:

```powershell
docker compose --profile bot up --build -d
```

Перевір worker:

```powershell
docker compose logs -f worker
```

## Якщо хочеш стару синхронну поведінку

У `.env` можна поставити:

```env
DOCUMENT_INDEXING_MODE=sync
```

Тоді API індексуватиме документ прямо під час upload. Для портфоліо краще лишити `async`.
