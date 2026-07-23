# AI Knowledge Assistant

A production-oriented multilingual RAG service for an internal company knowledge base. It combines FastAPI, PostgreSQL with pgvector, Redis-backed background indexing, local multilingual embeddings, OpenAI-compatible LLMs, document-level access control, feedback analytics, and an optional Telegram client.

Version `0.2.0` focuses on the features expected from a real internal AI product rather than a basic chat demo:

- workspace isolation;
- API identities with roles and groups;
- restricted documents with group ACLs;
- asynchronous document processing;
- hybrid vector and keyword retrieval;
- grounded answers with source labels;
- per-answer feedback;
- adoption and quality analytics;
- secure environment generation;
- automated CI and Docker build checks.

Ukrainian product notes are available in [`docs/COMPANY_BRAIN_UA.md`](docs/COMPANY_BRAIN_UA.md). Ukrainian startup instructions are in [`START_UA.md`](START_UA.md).

## Architecture

```text
REST / Telegram client
          |
          v
     API key identity
  workspace + role + groups
          |
          v
       FastAPI  -------- Redis rate limit
          |
          +---- Redis indexing queue + temporary upload bytes
          |                    |
          |                    v
          |                 Worker
          |                    |
          v                    v
     PostgreSQL + pgvector + document ACLs
          |
          v
 Hybrid vector + keyword retrieval
          |
          v
 OpenAI-compatible LLM endpoint
          |
          +---- chat log + feedback + analytics
```

Raw uploads are temporarily stored in Redis only while the worker indexes them. PostgreSQL stores document metadata, chunks, embeddings, chat logs, timings, actors, and feedback.

## Main features

### Document ingestion

- PDF, DOCX, and UTF-8 TXT uploads;
- content-based validation instead of trusting client MIME types;
- upload and extracted-text limits;
- DOCX paragraph and table extraction;
- asynchronous Redis-backed indexing worker;
- processing, ready, and failed statuses;
- local multilingual embeddings;
- HNSW vector index in PostgreSQL.

### Retrieval and answers

- workspace-scoped SQL queries;
- document ACL predicate applied during retrieval;
- vector similarity plus PostgreSQL full-text ranking;
- optional search within one selected document;
- source filenames, page numbers, excerpts, and similarity values;
- prompt-injection-resistant source framing;
- OpenAI-compatible Chat Completions client;
- provider-specific `reasoning_effort` disabled by default for local API compatibility.

### Corporate access control

Each API key maps to an identity:

```json
{
  "LONG_API_KEY": {
    "workspace_id": "company-a",
    "subject": "sales-user-1",
    "role": "viewer",
    "groups": ["sales"]
  }
}
```

Supported roles:

| Role | Permissions |
|---|---|
| `owner` | Full workspace access |
| `admin` | Document ACL management and analytics |
| `editor` | Upload and delete accessible documents |
| `viewer` | Read, chat, and rate own answers |

For backward compatibility, the old mapping remains valid:

```json
{"LONG_API_KEY":"company-a"}
```

Legacy values are interpreted as owner identities, so existing local configurations continue to work.

Documents can be:

- `workspace` — visible to all identities in the workspace;
- `restricted` — visible only to owner/admin identities or identities with a matching group.

The ACL is enforced when listing, opening, deleting, selecting, and retrieving document chunks. Workspace IDs are never accepted from request bodies.

## Quick start

### 1. Generate a secure `.env`

```bash
python scripts/init_env.py
```

The script creates separate random API and PostgreSQL secrets and refuses to overwrite an existing `.env` unless `--force` is explicitly supplied.

Never commit `.env`.

### 2. Configure an LLM

Local llama.cpp example:

```env
LLM_BASE_URL=http://host.docker.internal:8080/v1
LLM_API_KEY=local-not-secret
LLM_MODEL=deepseek
LLM_REASONING_EFFORT=
```

OpenAI-compatible cloud example:

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=YOUR_PROVIDER_KEY
LLM_MODEL=YOUR_MODEL
```

`LLM_REASONING_EFFORT` is optional. Leave it empty unless the selected provider explicitly supports that request field.

### 3. Start the stack

```bash
docker compose up --build -d
```

The API is bound to localhost:

```text
http://127.0.0.1:8000
```

Swagger is available in non-production mode:

```text
http://127.0.0.1:8000/docs
```

The API container automatically applies Alembic migrations before startup.

### 4. Upload a document

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/documents" \
  -H "X-API-Key: YOUR_EDITOR_OR_ADMIN_KEY" \
  -F "file=@policy.pdf"
```

Poll its status:

```bash
curl "http://127.0.0.1:8000/api/v1/documents/DOCUMENT_ID" \
  -H "X-API-Key: YOUR_KEY"
```

### 5. Restrict a document

```bash
curl -X PATCH "http://127.0.0.1:8000/api/v1/documents/DOCUMENT_ID/access" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_ADMIN_KEY" \
  -d '{"visibility":"restricted","allowed_groups":["hr","management"]}'
```

### 6. Ask a question

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_KEY" \
  -d '{"question":"What is the refund period?"}'
```

The response includes a `chat_id`, answer, and sources.

### 7. Save feedback

```bash
curl -X PUT "http://127.0.0.1:8000/api/v1/chat/CHAT_ID/feedback" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_KEY" \
  -d '{"rating":5,"comment":"Correct answer and source"}'
```

### 8. View business metrics

Owner/admin only:

```bash
curl "http://127.0.0.1:8000/api/v1/analytics/summary?days=30" \
  -H "X-API-Key: YOUR_ADMIN_KEY"
```

Metrics include document statuses, chat requests, unique API identities, average feedback rating, and feedback coverage.

## API endpoints

| Method | Endpoint | Access |
|---|---|---|
| `GET` | `/health` | Public service health |
| `POST` | `/api/v1/documents` | owner/admin/editor |
| `GET` | `/api/v1/documents` | authenticated + ACL |
| `GET` | `/api/v1/documents/{id}` | authenticated + ACL |
| `PATCH` | `/api/v1/documents/{id}/access` | owner/admin |
| `DELETE` | `/api/v1/documents/{id}` | owner/admin/editor + ACL |
| `POST` | `/api/v1/chat` | authenticated + ACL |
| `PUT` | `/api/v1/chat/{id}/feedback` | answer owner or admin |
| `GET` | `/api/v1/analytics/summary` | owner/admin |

Protected endpoints require:

```text
X-API-Key: your-key
```

## Telegram bot

Set:

```env
TELEGRAM_BOT_TOKEN=...
ALLOWED_TELEGRAM_USER_IDS=123456789
BACKEND_API_KEY=AN_OWNER_OR_ADMIN_KEY
```

Start it with:

```bash
docker compose --profile bot up --build -d
```

The bot supports document upload, indexing status, active-document selection, all-document search, health checks, and Redis-persisted selection state.

## Evaluation

Create a JSONL dataset based on `eval/questions.example.jsonl`, then run:

```bash
python eval/run_eval.py \
  --api-key YOUR_KEY \
  --base-url http://127.0.0.1:8000 \
  --file eval/questions.example.jsonl
```

The evaluator reports latency, expected source hits, expected answer terms, and citation rate. Feedback analytics add a second signal based on real user ratings.

## Security decisions

- API keys use constant-time comparison.
- Production mode rejects placeholder API and database secrets.
- Every protected data query includes workspace isolation.
- Restricted-document ACLs are enforced in SQL retrieval, not only in the UI.
- Duplicate upload errors do not reveal inaccessible restricted document IDs.
- Upload content is validated against the extension.
- File names are reduced to safe display basenames.
- Raw files have a Redis TTL and are deleted after indexing.
- Retrieved document text is explicitly treated as untrusted LLM input.
- CORS is disabled by default.
- Telegram access is denied by default.
- Redis rate limiting fails closed by default.
- Containers run as an unprivileged user with `no-new-privileges`.
- CI has read-only repository permissions and does not require secrets.

Prompt injection cannot be eliminated by prompting alone. Do not connect retrieved instructions directly to email, CRM, payment, or destructive tools without explicit authorization, parameter validation, and human approval.

## Development

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check .
ruff format --check .
```

PostgreSQL with pgvector and Redis are required for integration testing. Apply migrations with:

```bash
alembic upgrade head
```

Run API and worker separately:

```bash
uvicorn app.main:app --reload
python -m app.workers.indexer
```

## CI

GitHub Actions runs:

- Ruff linting;
- Ruff formatting checks;
- pytest;
- Python bytecode compilation;
- API Docker image build.

## Current limitations

- Static API keys are suitable for an internal demo but should be replaced with database-managed users, hashed credentials, and short-lived access tokens for a larger product.
- Async indexing temporarily stores raw bytes in Redis; large-scale production should use encrypted object storage.
- Scanned PDFs need an OCR pipeline.
- DOCX page numbers are unavailable because DOCX is flow-based.
- Hybrid retrieval does not replace a multilingual reranker.
- The Telegram bot uses one configured backend identity rather than per-user corporate SSO.

## Portfolio summary

> Built a production-oriented corporate RAG assistant with FastAPI, PostgreSQL/pgvector, Redis workers, multilingual embeddings, hybrid retrieval, document-level group ACLs, role-based API identities, grounded source citations, Telegram integration, user feedback analytics, Alembic migrations, automated tests, and GitHub Actions CI.
