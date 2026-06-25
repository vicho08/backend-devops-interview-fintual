# Backend/DevOps Engineer Interview

A small content service: users, posts, comments, tags. Django + Ninja + Postgres.

## Requirements

- Docker and Docker Compose

## Quick setup

1. Copy the environment variables file:
   ```bash
   cp .env.example .env
   ```
2. Start the environment:
   ```bash
   docker compose up --build
   ```
3. Apply migrations:
   ```bash
   docker compose exec web uv run python manage.py migrate
   ```
4. Load sample data (fast seed for development):
   ```bash
   docker compose exec web uv run python manage.py seed --fast
   ```

The app is available at http://localhost:8000. API docs at http://localhost:8000/api/docs.

## Environment variables

See `.env.example` for the full list of available variables.
Inside Docker, `POSTGRES_HOST` must be `db`; outside Docker, `localhost`.

## Development

- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`
- Tests: `uv run pytest`
- CI runs lint and tests automatically on every push/PR.

## Seed

- `manage.py seed` — full dataset (~100k posts, ~500k comments; takes several minutes).
- `manage.py seed --fast` — minimal dataset for development (seconds).

## API

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET    | `/api/posts` | Published posts, newest first |
| GET    | `/api/posts/search?q=` | Full-text-ish search across title and body |
| GET    | `/api/posts/by-tag/{slug}` | Posts carrying a given tag |
| GET    | `/api/posts/{id}` | Post detail with comments |
| POST   | `/api/posts` | Create a post |
| POST   | `/api/posts/{id}/comments` | Add a comment to a post |
| GET    | `/api/users/{id}` | User profile with post and comment counts |
| GET    | `/api/users/find?email=` | Look up a user by email |
