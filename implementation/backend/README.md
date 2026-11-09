# Kuku screenplay processing and promo finder

Start with [PROCESSING.md](PROCESSING.md) for the standalone scene-analysis and LangGraph promo-generation workflow. The API scaffolding below is optional and is not needed for processing.

# Kuku processing API

Phase 1 backend: projects, atomic screenplay upload, deterministic parsing, durable processing jobs, optional AI episode analysis, and source-grounded episode annotations. Promo length is fixed at 20–60 seconds. Prompt-based promo generation and the frontend are later phases.

## Local setup

Python 3.12+ recommended. From `backend/`:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
set -a
source .env
set +a
uvicorn app.main:app --reload --port 8000
```

In a second terminal, activate the same environment and load `.env`, then:

```sh
python -m app.worker
```

Interactive endpoint documentation: http://localhost:8000/docs

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | DB connectivity, AI configuration, fixed promo limits |
| POST | `/projects` | Create with `{"name":"My series"}` |
| GET | `/projects` | Project inventory |
| GET | `/projects/{id}` | Counts and latest job |
| POST | `/projects/{id}/episodes` | Multipart `files` uploads; UTF-8 `.txt`, 2 MiB each, maximum 200 |
| GET | `/projects/{id}/episodes` | Summaries and parsing statistics |
| GET | `/projects/{id}/episodes/{number}` | Original source, scenes, timed blocks, AI analysis |
| POST | `/projects/{id}/process` | `{"mode":"parse"}` or `{"mode":"analyze"}`; returns job ID |
| GET | `/jobs/{id}` | Durable status, progress, error, result |
| GET | `/projects/{id}/runs?limit=50&offset=0` | Unedited model responses and prompts; authenticated |

When APP_API_KEY is configured, pass `X-API-Key` to project/job routes. This is single-workspace access protection, not multi-user authentication. Do not embed that key into a public frontend; add user sessions or a server-side frontend proxy before shared hosting.

Uploads parse immediately so bad files are rejected before committing. A batch is atomic. Identical reuploads are safe; a changed existing episode returns 409. The worker's parse job finalizes project metadata; analyze adds AI episode annotations. Existing successful analyses are reused after failure/restart. No external model is called on upload.

## AI configuration

Set LLM_BASE_URL, LLM_MODEL and LLM_API_KEY to a compatible chat-completions provider. The provider must support JSON-object response format and enough context for an episode. The API key stays on the backend. Only `analyze` sends source content externally. Verify your chosen provider is appropriate for confidential assignment content.

No model configured means parsing works and analysis returns 503. Source loglines are explicitly preserved as source metadata, not advertised as generated summaries. Invalid JSON or invented evidence references fail the job; raw responses are preserved. Analysis contains an episode summary and scene-level tags, hooks, endings, open questions, context requirements and source references. Automatic continuous promo discovery is implemented by the standalone LangGraph workflow. Prompt-based search and the interface remain to implement.

## Deployment

```sh
cp .env.example .env
# Set APP_API_KEY, model credentials, and exact frontend origin in .env.
docker compose up --build -d
```

Deploy API and exactly **one worker** on the same machine with the shared persistent `/data` volume. SQLite WAL requires a local filesystem; do not place it on a network filesystem or run workers on separate hosts. The worker supports crash recovery, but not concurrent workers. Use PostgreSQL and leased queue jobs before horizontal scaling. A restart may repeat an in-flight model request; completed episode results are cached.

For a VPS, terminate HTTPS at a reverse proxy and keep port 8000 private behind it. Back up the persistent volume. For managed hosting, choose persistent disk support and colocate both processes, or migrate storage/queue before deploying separate services. Ephemeral/serverless storage will lose projects and is not supported by this setup.

Do not commit `.env`, project databases, raw model runs, or confidential screenplay files. The Docker build copies only application code and requirements, not the input pack.

## Verification

```sh
python -m unittest discover -s tests -v
python -m compileall -q app
```

The optional supplied-pack test checks all 50 scripts. AI quality requires a configured model and manual review; offline tests do not establish summary accuracy.
