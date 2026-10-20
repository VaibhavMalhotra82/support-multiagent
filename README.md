# Technical Support Multi-Agent Solution

This repository contains a support portal and AI-assisted backend for technical support workflows. It includes a FastAPI service with role-based access control, a Vite + React UI for support operators, and a multi-agent workflow for support queries, feedback, and RCA records.

## Overview

- FastAPI service for request handling and RBAC-protected endpoints
- SQLite-based authentication and RBAC model
- Caching and retrieval abstractions for support knowledge queries
- Multi-turn memory and observability hooks
- Root cause analysis and feedback capture
- React-based support portal with login, query, feedback, and RCA forms

## Project Structure

- `app/main.py` — FastAPI composition root, routes, and CORS configuration
- `app/config/` — application settings and environment configuration
- `app/db/` — SQLAlchemy models, engine, sessions, and schema initialization
- `app/auth/` — authentication, token lifecycle, and RBAC utilities
- `app/cache/` — in-memory and Redis cache backends
- `app/knowledge/` — document ingestion and retrieval
- `app/memory/` — conversation and long-term memory services
- `app/persistence/` — RCA persistence and search
- `app/observability/` — structured logging and telemetry helpers
- `app/contracts/` — API schemas and workflow state contracts
- `app/workflow/` — prompts, agent nodes, and LangGraph workflow orchestration
- `ui/` — Vite React frontend for the support portal

## Quick start

### 1) Backend (FastAPI)

From the repository root:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:

- http://localhost:8000
- Swagger docs: http://localhost:8000/docs

### 2) Frontend (React + Vite)

Open a second terminal and run:

```bash
cd ui
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

The UI will be available at:

- http://localhost:5173

### 3) Run both together

Use two terminals at the same time:

- Terminal 1: backend
- Terminal 2: frontend

This is required because the UI calls the API at `http://localhost:8000` and the backend allows requests from `http://localhost:5173` via CORS.

## Demo credentials

The seeded demo users are:

- support / support123
- admin / admin123
- user / user123

## Notes

This implementation includes the login compatibility route for `/login` as well as `/auth/login` and uses local storage in the UI to keep a user session between refreshes. The retrieval and LLM integration are designed to be replaced with your preferred vector store, search engine, and model provider.

## Conversation memory

Conversation turns and long-term Q&A summaries are stored in the configured SQL database. Set `DATABASE_URL` in `.env` to change the database location; the default is `sqlite:///./support_agent.db`.

The browser keeps one conversation ID per logged-in username and sends it with each query. Conversation history is scoped to the authenticated user and tenant. Long-term summaries are also indexed in a separate persistent Chroma collection for semantic recall; SQL remains the authoritative store if the vector index is unavailable.

When upgrading an existing SQLite database, application startup adds the new `query_records.session_id` column and creates the memory tables. For other database engines, use the equivalent schema migration before deploying.

## Document ingestion

Administrators can ingest documents from the UI or through `POST /admin/ingest`. The API accepts a local path or an HTTP(S) URL in the `source` field. `POST /admin/sync` uses the same source handling while replacing existing chunks for the source.

Supported sources:

- Local UTF-8 text files, supplied as a filesystem path or `pathlib.Path`.
- `http://` and `https://` URLs returning text content.
- HTML pages from local `.html`/`.htm` files or HTTP responses with `text/html` content type. Script, style, and noscript content is removed before indexing.

When the source is an HTTP(S) URL, ingestion follows links on the same host whose paths remain under the source path. For example, ingesting `https://www.mkdocs.org/user-guide` also follows pages such as `https://www.mkdocs.org/user-guide/configuration/`, but excludes external hosts and unrelated paths such as `/about/`. URL fragments and query strings are ignored, and crawling is limited to 100 pages per source.

Each source is split into overlapping chunks and stored in the configured Chroma collection. The default chunk size is 1,000 characters with 150 characters of overlap. Every chunk receives standard source metadata: `source`, `source_type`, `content_type`, `file_extension`, and either file fields (`file_name`) or URL fields (`url_host`, `url_path`). HTML pages also include `title` and normalized `html_meta_*` values when present. Custom metadata can be attached during ingestion and used by retrieval filters. For crawled URLs, custom metadata is inherited by every child page; custom values override derived values except for the immutable `source` and `document_id` fields.

The current ingestion pipeline does not provide specialized parsing for PDF, DOCX, XLSX, images, binary files, directories, FTP URLs, or other URL schemes. Those sources should be converted to UTF-8 text or handled by a format-specific ingestion adapter before submission.

Example:

```bash
curl -X POST http://localhost:8000/admin/ingest \
	-H "Authorization: Bearer <ADMIN_TOKEN>" \
	-H "Content-Type: application/json" \
	-d '{"source": "README.md", "metadata": {"product": "MkDocs", "version": "1.0", "tags": ["documentation"]}}'
```

## Redis

Redis is included as an optional distributed-cache backend. Its connection settings are `REDIS_HOST`, `REDIS_PORT`, and `REDIS_DB`; Docker Compose starts Redis automatically and configures the API to use the `redis` service name.

The current retrieval path uses the in-process `InMemoryCache` by default, so local development does not require Redis. To use the distributed backend, wire `RedisCache` into the retrieval cache configuration before deployment; Redis is not currently selected automatically from environment variables.

## Admin operations

Admin users can click any card in the Operational stats section to load its current detail rows: active users, resolved queries, cache hits, or open escalations. Detail data is admin-only, paginated, and intentionally excludes full support questions and answers.

Backend logs use a consistent verbose format with the timestamp, level, source filename and line, process identity, workflow step, request ID, and event message. Workflow steps include `query.request`, `workflow.retrieve_documents`, `workflow.generate_answer`, `workflow.decide_escalation`, and `query.response`. Request and response logs include serialized payloads with sensitive values redacted.

The admin console's Recent activity section is backed by `GET /admin/activity`. It records durable login, logout, query, feedback, RCA, ingestion, and document sync events in the `activity_events` table. Results are newest-first and support `limit` and `offset` pagination.

Authentication uses expiring bearer session tokens. `POST /auth/logout` revokes all active sessions for the authenticated user; the UI calls this endpoint before clearing its local session. Existing SQLite databases receive the `session_tokens.revoked_at` column during application startup.
