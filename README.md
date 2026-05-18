# JobFit OS

JobFit OS is a FastAPI application for job discovery, resume-aware scoring, scheduled briefings, and resume rewrite workflows. The backend serves a self-contained static frontend from `static/index.html`, so there is no JavaScript build step or npm dependency.

## Features

- User onboarding with management-token based local auth
- Resume upload from PDF or pasted text
- Profile preferences for target companies, salary, remote work, and keywords
- Configurable scoring weights
- Manual and scheduled briefing runs
- Email delivery for job briefings and tailored resume rewrites
- Render deployment configuration with managed Postgres

## Tech Stack

- FastAPI
- SQLAlchemy async ORM
- Alembic migrations
- PostgreSQL in production and local Docker
- SQLite-compatible test path
- Vanilla HTML, CSS, and JavaScript frontend

## Project Structure

```text
app/
  main.py              FastAPI app, routers, static file serving
  models/             SQLAlchemy models
  routers/            API routes
  schemas/            Pydantic schemas
  services/           Email, scheduling, PDF parsing, docx generation
  pipeline/           Discovery, scoring, rewrite pipeline
alembic/              Database migrations
static/index.html     Single-file frontend
tests/                Pytest suite
render.yaml           Render deployment config
docker-compose.yml    Local Postgres service
```

## Local Setup

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy the example environment and fill in secrets as needed:

```bash
cp .env.example .env
```

Start Postgres locally:

```bash
docker compose up -d
```

Run migrations:

```bash
alembic upgrade head
```

Start the app:

```bash
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

## Static Frontend

The frontend is served directly by FastAPI:

- `GET /` returns `static/index.html`
- `GET /static/index.html` serves the same file through static hosting

The frontend stores `{ user_id, management_token }` in `localStorage` under `jobfit_user`. Authenticated API calls send:

```text
Authorization: Bearer <management_token>
```

If an API call returns `401` or `403`, local storage is cleared and onboarding is shown again.

## Tests

For a local SQLite-backed test run:

```bash
DATABASE_URL=sqlite+aiosqlite:///./jobfit_os_test.db pytest
```

## Deployment

`render.yaml` defines:

- Python web service
- Render Postgres database
- Build command: `pip install -r requirements.txt && alembic upgrade head`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

Set these secrets in Render:

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `GMAIL_ADDRESS`
- `GMAIL_APP_PASSWORD`

Render generates `JWT_SECRET` automatically.

## Notes

- Do not commit `.env`, local databases, virtual environments, or cache directories.
- The app expects UUID columns in Postgres; keep SQLAlchemy model UUID types aligned with Alembic migrations.
