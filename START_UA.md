# Швидкий запуск українською

## 1. Створи `.env` із безпечними випадковими ключами

У корені проєкту виконай:

```powershell
python scripts/init_env.py
```

Скрипт створить окремі випадкові значення для API-ключа та пароля PostgreSQL. Файл `.env` не додається до Git.

Якщо переносиш старий `.env`, додай нові змінні:

```env
DOCUMENT_INDEXING_MODE=async
DOCUMENT_RAW_TTL_SECONDS=3600
RAG_HYBRID_SEARCH=true
RAG_KEYWORD_WEIGHT=0.25
RAG_CANDIDATE_MULTIPLIER=4
```

## 2. Налаштуй локальну LLM

Для твого llama.cpp у `.env` залиш:

```env
LLM_BASE_URL=http://host.docker.internal:8080/v1
LLM_API_KEY=local-not-secret
LLM_MODEL=deepseek
```

Сервер потрібно запускати з доступом для Docker:

```powershell
llama-server.exe `
  -m C:\Python\ai\models\deepseek-coder-6.7b-instruct.Q4_K_M.gguf `
  --host 0.0.0.0 `
  --port 8080 `
  -ngl 35 `
  -c 4096 `
  --alias deepseek
```

Не відкривай порт 8080 для зовнішньої мережі. Дозволь доступ лише локально або для Docker через Windows Firewall.

## 3. Запусти API + worker

```powershell
docker compose up --build -d
```

Тепер, крім `api`, запускається ще `worker`. Саме він індексує документи у фоні.

Перевір:

```text
http://127.0.0.1:8000/docs
```

Логи:

```powershell
docker compose logs -f api
docker compose logs -f worker
```

## 4. Додай документ

У Swagger відкрий `POST /api/v1/documents`, натисни `Try it out`, додай заголовок `X-API-Key` і вибери PDF, DOCX або UTF-8 TXT.

API-ключ лежить у `.env` всередині `API_KEYS_JSON`.

Після upload документ може мати статус:

```text
processing — worker ще індексує
ready — можна ставити питання
failed — індексація не вдалася, дивись error_message
```

Статус можна перевірити через:

```text
GET /api/v1/documents/{document_id}
```

## 5. Постав запитання

Використай `POST /api/v1/chat`:

```json
{
  "question": "Про що йдеться в документі?"
}
```

Або для конкретного документа:

```json
{
  "question": "Про що йдеться в цьому документі?",
  "document_id": "UUID_ДОКУМЕНТА"
}
```

Система знайде релевантні фрагменти через hybrid retrieval: pgvector similarity + PostgreSQL full-text rank. У відповіді API повертаються назви файлів, сторінки та similarity score.

## Telegram-бот

Заповни в `.env`:

```env
TELEGRAM_BOT_TOKEN=...
ALLOWED_TELEGRAM_USER_IDS=твій_числовий_telegram_id
```

Потім:

```powershell
docker compose --profile bot up --build -d
```

Порожній allow-list навмисно блокує запуск бота, щоб сторонні люди не могли витрачати ресурси LLM.

Бот тепер чекає, поки worker закінчить індексацію. Коли документ стає `ready`, бот автоматично вибирає його активним.

Активний документ зберігається в Redis, тому після рестарту бота вибір не зникає.

## Eval-перевірка RAG

Після того як додаси документи, можна створити свій файл питань за прикладом `eval/questions.example.jsonl` і запустити:

```powershell
python eval/run_eval.py --api-key YOUR_LONG_RANDOM_KEY --file eval/questions.example.jsonl
```

Скрипт покаже latency, source hit rate, citation rate і попадання очікуваних термінів.

## Якщо хочеш стару поведінку без worker

У `.env` постав:

```env
DOCUMENT_INDEXING_MODE=sync
```

Тоді документ буде індексуватися прямо під час upload, як раніше. Для портфоліо краще лишити `async`, бо це ближче до production.

## Корисні команди

```powershell
docker compose ps
docker compose logs -f api
docker compose logs -f worker
docker compose --profile bot logs -f bot
docker compose down
```

Повне технічне пояснення, архітектура, API, обмеження та напрямки розвитку описані в `README.md`.
