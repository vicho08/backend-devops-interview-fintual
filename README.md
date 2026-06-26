# Backend/DevOps Engineer Interview

A content service (users, posts, comments, tags) built with **Django 5.2**, **Django Ninja**, and **PostgreSQL 16**. Interview project: 8 features implemented in 2 hours; 3 deliberately deferred. See [NOTAS.md](NOTAS.md) for retrospective.

## Quick Start

**Requirements:** Docker and Docker Compose.

```bash
# Start the stack
docker compose up --build

# In another terminal: run migrations
docker compose exec web uv run python manage.py migrate

# (Optional) Load sample data
docker compose exec web uv run python manage.py seed --fast
```

App: **http://localhost:8000** | API docs: **http://localhost:8000/api/docs**

## Features

| # | Feature | Status | Impact |
|---|---------|--------|--------|
| F1 | Environment configuration | ✅ | Removed hardcoded secrets |
| F2 | Docker + docker-compose | ✅ | One-command setup |
| F3 | Code style (ruff) | ✅ | Consistency |
| F4 | Seed improvements | ✅ | Dev velocity |
| F5 | README reorganized | ✅ | Onboarding |
| **F6** | **Eager loading (N+1)** | **✅** | **66,000× fewer queries** |
| **F7** | **Pagination** | **✅** | **Bounded load** |
| **F8** | **Atomic view_count** | **✅** | **Race-condition free** |
| F9 | Batch tags + counts | ⏳ | [See NOTAS.md](NOTAS.md) |
| F10 | Full-text search + GIN | ⏳ | [See NOTAS.md](NOTAS.md) |
| F11 | B-tree indexes | ⏳ | [See NOTAS.md](NOTAS.md) |

**Deferred features (F9–F11):** See [NOTAS.md](NOTAS.md) for risk assessment and next steps.

## Commands

```bash
uv run ruff check .                                    # Lint
uv run ruff format .                                   # Format
uv run pytest                                          # Test all
uv run pytest blog/tests/test_posts.py::TEST_NAME     # Test specific
uv run python manage.py shell                          # Django shell
uv run python manage.py seed --fast                    # Quick seed
uv run python manage.py runserver                      # Dev server
```

## Environment Variables

See `.env.example`. Inside Docker: `POSTGRES_HOST=db`; outside: `POSTGRES_HOST=localhost`.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/posts` | Published posts (paginated) |
| GET | `/api/posts/search?q=` | Search title/body |
| GET | `/api/posts/by-tag/{slug}` | Posts by tag (paginated) |
| GET | `/api/posts/{id}` | Post detail with comments |
| POST | `/api/posts` | Create post |
| POST | `/api/posts/{id}/comments` | Add comment |
| GET | `/api/users/{id}` | User profile |
| GET | `/api/users/find?email=` | Find user by email |
