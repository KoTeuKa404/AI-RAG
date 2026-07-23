# AI Knowledge Assistant

Production-oriented RAG portfolio project built with FastAPI, PostgreSQL + pgvector, Redis, a background indexing worker, local multilingual embeddings, an OpenAI-compatible LLM endpoint, hybrid retrieval, and an optional Telegram bot.

The application accepts PDF, DOCX, and UTF-8 TXT files, validates their content, creates document records, indexes them asynchronously, stores chunks and embeddings in PostgreSQL, retrieves relevant fragments, and asks an LLM to answer with source labels.

For Ukrainian setup instructions, see `START_UA.md`. For the upgrade notes, see `docs/UPGRADE_UA.md`.

## Main features

- FastAPI REST API
- PDF, DOCX, and TXT ingestion
- Content-based file validation
- Asynchronous document indexing through Redis + worker
- `processing` / `ready` / `failed` document statuses
- DOCX paragraph and table extraction
- Local multilingual embeddings
- PostgreSQL with pgvector and HNSW vector search
- Hybrid retrieval: vector similarity + PostgreSQL full-text rank
- OpenAI-compatible Chat Completions client
- Support for OpenAI cloud, llama.cpp, LM Studio, Ollama-compatible gateways, and similar endpoints
- Workspace isolation through API keys
- Source metadata and page numbers
- Prompt-injection-resistant RAG prompt
- Redis-backed request rate limiting
- Telegram bot with an allow-list
- Telegram active-document state persisted in Redis
- Alembic migrations
- Docker Compose with `api`, `worker`, `postgres`, `redis`, and optional `bot`
- Basic RAG eval script
- Tests for chunking, file validation, DOCX table extraction, and queue payloads

## Architecture

```text
Telegram / REST client
          |
          v
       FastAPI  ---- Redis rate limit
          |
          +---- Redis indexing queue + temporary raw upload bytes
          |              |
          |              v
          |          Worker
          |              |
          v              v
    PostgreSQL + pgvector chunks
          |
          v
Hybrid retrieval: vector search + keyword rank
          |
          v
OpenAI-compatible LLM
```

Uploaded raw files are stored only temporarily in Redis while the worker indexes them. After indexing, the worker deletes the temporary raw bytes. PostgreSQL stores document metadata, extracted chunks, embeddings, and chat logs.

## Quick start

### 1. Create the environment file

The recommended method generates separate random API and database secrets:

```bash
python scripts/init_env.py
```

Alternatively, copy `.env.example` manually and generate strong random values. Put the API key into both API-key fields, and set a separate database password:

```env
POSTGRES_PASSWORD=YOUR_DATABASE_PASSWORD
DATABASE_URL=postgresql+asyncpg://rag:YOUR_DATABASE_PASSWORD@postgres:5432/rag
API_KEYS_JSON={"YOUR_LONG_RANDOM_KEY":"demo-workspace"}
BACKEND_API_KEY=YOUR_LONG_RANDOM_KEY
```

Do not commit `.env`.

### 2. Configure the LLM

#### Local llama.cpp server

The default configuration expects llama.cpp on the host machine:

```env
LLM_BASE_URL=http://host.docker.internal:8080/v1
LLM_API_KEY=local-not-secret
LLM_MODEL=deepseek
```

Example llama.cpp command:

```powershell
llama-server.exe `
  -m C:\Python\ai\models\deepseek-coder-6.7b-instruct.Q4_K_M.gguf `
  --host 0.0.0.0 `
  --port 8080 `
  -ngl 35 `
  -c 4096 `
  --alias deepseek
```

Using `0.0.0.0` is required for Docker to reach the host service. Restrict the port with Windows Firewall so it is not exposed to untrusted networks.

#### OpenAI cloud

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=YOUR_PROVIDER_KEY
LLM_MODEL=YOUR_CHAT_MODEL
```

### 3. Start the API and worker

```bash
docker compose up --build -d
```

The first startup can take longer because the multilingual embedding model is downloaded into the Docker volume. The `worker` service shares the same Hugging Face cache volume as the API.

Open API documentation in development mode:

```text
http://127.0.0.1:8000/docs
```

### 4. Upload a document

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/documents" \
  -H "X-API-Key: YOUR_LONG_RANDOM_KEY" \
  -F "file=@example.pdf"
```

The response usually returns `status: processing`. Check status:

```bash
curl "http://127.0.0.1:8000/api/v1/documents/DOCUMENT_ID" \
  -H "X-API-Key: YOUR_LONG_RANDOM_KEY"
```

Ask questions only when the document status is `ready`.

### 5. Ask a question

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_LONG_RANDOM_KEY" \
  -d '{"question":"What does the document say about refunds?"}'
```

To limit search to one document:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_LONG_RANDOM_KEY" \
  -d '{"question":"What does this file say?", "document_id":"DOCUMENT_ID"}'
```

### 6. List documents

```bash
curl "http://127.0.0.1:8000/api/v1/documents" \
  -H "X-API-Key: YOUR_LONG_RANDOM_KEY"
```

## Telegram bot

Create a bot token and set:

```env
TELEGRAM_BOT_TOKEN=...
ALLOWED_TELEGRAM_USER_IDS=123456789
```

The allow-list is intentionally mandatory. An empty list prevents the bot from starting, which avoids accidentally exposing a paid LLM endpoint to everyone.

Start the bot profile:

```bash
docker compose --profile bot up --build -d
```

The bot accepts supported documents, sends them to the API, waits for indexing to finish, and selects the ready document as active. Active document selection is stored in Redis, so it survives bot restarts.

Useful commands:

```text
/documents — choose an active document
/current — show current search mode
/all — search across all ready documents
/health — check API, PostgreSQL, and Redis
```

## Workspace isolation

`API_KEYS_JSON` maps API keys to workspace IDs:

```env
API_KEYS_JSON={"key-for-team-a":"team-a","key-for-team-b":"team-b"}
```

Every document, chunk, retrieval query, deletion, and chat log is filtered by the authenticated workspace. A client cannot select its own workspace ID in a request body.

Use long random keys. For a larger product, replace static API keys with user accounts, short-lived access tokens, and hashed credentials stored in the database.

## Security decisions

- The server validates file content instead of trusting only extensions or client MIME types.
- File names are reduced to a basename and are never used as storage paths.
- Upload and extracted-text limits reduce memory and cost abuse.
- Raw files are stored temporarily in Redis only for async indexing and are deleted after worker success.
- SQLAlchemy generates parameterized SQL.
- Document text is treated as untrusted input in the LLM prompt.
- The model is instructed not to obey commands found inside documents.
- API keys are compared with constant-time comparison.
- CORS is disabled by default.
- Telegram access is denied by default.
- Redis rate limiting fails closed by default.
- Containers run as an unprivileged user with `no-new-privileges`.
- Secrets stay in `.env`, which is ignored by Git.

Important limitation: prompt-injection protection cannot be guaranteed by a prompt alone. High-risk actions should never be directly executable from retrieved documents. Add explicit authorization and human confirmation before integrating email, CRM changes, payments, or destructive tools.

## Configuration

Important variables:

| Variable | Purpose |
|---|---|
| `API_KEYS_JSON` | API key to workspace mapping |
| `DOCUMENT_INDEXING_MODE` | `async` for worker queue, `sync` for old inline indexing |
| `DOCUMENT_RAW_TTL_SECONDS` | Temporary Redis TTL for raw bytes waiting for worker |
| `LLM_BASE_URL` | OpenAI-compatible `/v1` base URL |
| `LLM_MODEL` | Provider model or local alias |
| `EMBEDDING_MODEL` | Sentence Transformers model |
| `EMBEDDING_DIMENSION` | Must match the selected model |
| `CHUNK_SIZE` | Approximate chunk size in characters |
| `CHUNK_OVERLAP` | Repeated characters between chunks |
| `RAG_TOP_K` | Maximum retrieved chunks |
| `RAG_MIN_SIMILARITY` | Minimum cosine similarity unless keyword rank matches |
| `RAG_HYBRID_SEARCH` | Enable vector + keyword retrieval |
| `RAG_KEYWORD_WEIGHT` | Weight of full-text rank in hybrid ordering |
| `RAG_CANDIDATE_MULTIPLIER` | Candidate pool multiplier before final top-k trim |
| `MAX_UPLOAD_BYTES` | Upload memory limit |
| `CHAT_RATE_LIMIT_PER_MINUTE` | Requests per workspace per minute |

The default embedding model produces 384-dimensional vectors. Changing the model or vector dimension requires a database migration and rebuilding the document index.

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Database and Redis health |
| `POST` | `/api/v1/documents` | Upload a document and enqueue indexing |
| `GET` | `/api/v1/documents` | List workspace documents |
| `GET` | `/api/v1/documents/{id}` | Get document status |
| `DELETE` | `/api/v1/documents/{id}` | Delete a workspace document |
| `POST` | `/api/v1/chat` | Ask a RAG question |

Protected endpoints require:

```text
X-API-Key: your-key
```

## Evaluation

Create or edit a JSONL file similar to `eval/questions.example.jsonl`, then run:

```bash
python eval/run_eval.py \
  --api-key YOUR_LONG_RANDOM_KEY \
  --base-url http://127.0.0.1:8000 \
  --file eval/questions.example.jsonl
```

The script reports latency, source hit rate, expected terms hit rate, and citation rate. This is intentionally simple and suitable for a portfolio project; production evaluation should include larger datasets and human review.

## Development without Docker

Create a virtual environment and install development dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

You still need PostgreSQL with pgvector and Redis. Set `DATABASE_URL` and `REDIS_URL`, then run:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

Run the worker in another terminal:

```bash
python -m app.workers.indexer
```

Tests:

```bash
pytest -q
```

Linting:

```bash
ruff check .
ruff format --check .
```

## Current limitations

- Async indexing stores raw bytes temporarily in Redis. For larger production use, replace this with encrypted object storage.
- DOCX does not provide reliable page numbers because the format is flow-based.
- Scanned PDFs require a separate OCR pipeline.
- Hybrid retrieval does not replace a proper reranker.
- Chat history is logged but not inserted into the prompt.
- API keys are static configuration rather than database-managed identities.
- The LLM client uses Chat Completions for broad local-provider compatibility.

## Recommended next steps

1. Add encrypted object storage for raw-file retention and reindexing.
2. Add a multilingual cross-encoder reranker.
3. Add larger evaluation datasets for retrieval recall and grounded answers.
4. Add structured logging, OpenTelemetry, and metrics.
5. Add a small React or server-rendered admin interface.
6. Add role-based access and document-level ACLs.
7. Add CI with tests, linting, and Docker build checks.

## CV description

> Developed a production-oriented multilingual RAG assistant using FastAPI, PostgreSQL with pgvector, Redis, Docker, local embeddings, an OpenAI-compatible LLM API, asynchronous document indexing, hybrid retrieval, source citations, Telegram integration, migrations, and automated tests.
