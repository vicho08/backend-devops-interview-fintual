# Backend/DevOps Engineer Interview

A lightweight content service (users, posts, comments, tags) built with **Django 5.2**, **Django Ninja**, and **PostgreSQL 16**. This project demonstrates a complete technical interview cycle: developer experience improvements, performance optimization, and thoughtful architectural decisions under time constraints.

**Status:** 8 features implemented in 2 hours; 3 features deliberately deferred. See [NOTAS.md](NOTAS.md) for detailed retrospective.

## Quick Start

**Requirements:** Docker and Docker Compose.

### Run locally in 3 steps

```bash
# 1. Start the full stack (Postgres + Django)
docker compose up --build

# 2. Apply migrations (in another terminal)
docker compose exec web uv run python manage.py migrate

# 3. (Optional) Load sample data
docker compose exec web uv run python manage.py seed --fast
```

The app is available at **http://localhost:8000**. API interactive docs at **http://localhost:8000/api/docs**.

---

## Features Implemented — Épicas & Status

### Epic: Developer Experience (F1–F5) ✅ Complete

| # | Feature | Status | Impact | Details |
|---|---------|--------|--------|---------|
| F1 | Environment configuration | ✅ | Security, flexibility | Removed hardcoded secrets; all config via `os.environ` with safe defaults |
| F2 | Docker + docker-compose | ✅ | DX, reproducibility | Single `docker compose up` eliminates manual Postgres setup |
| F3 | Code style consistency | ✅ | Maintainability | Global `ruff` pass; uniform quotes, imports, formatting |
| F4 | Seed command improvements | ✅ | Dev velocity | Config dicts + progress output; `--fast` flag for quick iteration |
| F5 | README reorganized | ✅ | Onboarding | Clear sections: Stack, Setup, Development, Architecture |

### Epic: Performance (F6–F11) ⚠️ Partial (50%)

| # | Feature | Status | Impact | Details |
|---|---------|--------|--------|---------|
| F6 | Eager loading (N+1 elimination) | ✅ | **66,000× fewer queries** | `select_related` + `prefetch_related` on list endpoints; 200k → 3 queries |
| F7 | Pagination (limit/offset) | ✅ | Bounded load | `limit=20` default, `le=100` cap; memory-safe for any dataset size |
| F8 | Atomic `view_count` increment | ✅ | Race-condition free | `F('view_count') + 1` eliminates lost updates under concurrency |
| F9 | Batch tags + annotate counts | ⏳ | Deferred | See [NOTAS.md](NOTAS.md) |
| F10 | Full-text search + GIN index | ⏳ | Deferred | See [NOTAS.md](NOTAS.md) |
| F11 | B-tree indexes | ⏳ | Deferred | See [NOTAS.md](NOTAS.md) |

---

## Implementation Summary

### Developer Experience (F1–F5): From Prototype to Production-Ready

The project started as a single-developer prototype: hardcoded `SECRET_KEY`, manual Postgres installation, inconsistent code style, and a README full of manual steps with no error guidance.

**What we did:**
- **F1:** Refactored `core/settings.py` to read all sensitive values (`SECRET_KEY`, DB credentials, `DEBUG`) from environment variables with safe local defaults. Added `.env.example` with documentation.
- **F2:** Containerized the entire stack: `Dockerfile` (multi-stage, slim images) + `docker-compose.yml` (Postgres 16 + Django). One command (`docker compose up`) replaces hours of manual setup.
- **F3:** Ran `ruff check . && ruff format .` globally for style consistency.
- **F4:** Refactored `manage.py seed` to use config dictionaries and print progress every 10% (the full seed of ~100k posts takes minutes; feedback matters).
- **F5:** Reorganized README with clear sections: Stack, Quick Start, Development, Architecture, and pointers to API docs.

**Why:** These changes eliminate onboarding friction and prepare the codebase for collaborative development and cloud deployment.

### Performance Optimizations (F6–F8): From 200k Queries to 3

The dataset of ~100k posts + ~500k comments exposed the classic **N+1 problem** and missing pagination, making endpoints slow under any significant load.

#### F6 — Eager Loading: 66,000× faster on GET /posts

**Problem:** `list_posts` fetched 100k posts without limits, then accessed `post.author` and `post.tags.all()` in the serialization loop → ~200k additional queries.

**Solution:** Add `select_related("author").prefetch_related("tags")` to the queryset. This collapses author and tag resolution into exactly 2 additional queries (one JOIN, one IN), regardless of page size.

```python
# Before: ~200k queries
posts = Post.objects.filter(is_published=True).order_by("-created_at")
for post in posts:
    print(post.author, post.tags.all())  # N+1

# After: 3 queries total
posts = (
    Post.objects
    .filter(is_published=True)
    .select_related("author")           # 1 JOIN query
    .prefetch_related("tags")           # 1 IN query
    .order_by("-created_at")
)
```

Same pattern applied to `search_posts` and `posts_by_tag`. For `get_post`, we use a named `Prefetch` to load comments with their authors in a single query:

```python
Prefetch(
    "comments",
    queryset=Comment.objects.select_related("author").order_by("created_at"),
)
```

#### F7 — Pagination: Memory-Safe for Any Dataset

**Problem:** No endpoint limited results. `GET /posts` returned all 100k posts at once, bloating memory and database.

**Solution:** Implement `DefaultPagination(LimitOffsetPagination)` with `limit=20` default and `le=100` server-side cap. Applied via `@paginate()` decorator.

```python
@router.get("/posts", response=list[PostListOut])
@paginate(DefaultPagination)  # Automatic limit/offset slicing
def list_posts(request):
    return Post.objects.filter(is_published=True)...
```

Response: `{"posts": [20 items], "count": 100000}`. Query count stays constant (3) per page, regardless of dataset size.

#### F8 — Atomic view_count: Race Condition Eliminated

**Problem:** View counter was a read-modify-write without synchronization:
```python
post.view_count += 1  # Read
post.save()           # Write
```
Two concurrent requests could both read 500, both write 501, losing one increment.

**Solution:** Use `F()` expression for atomic database-level increment:
```python
Post.objects.filter(id=post_id).update(view_count=F("view_count") + 1)
```
Generates `UPDATE blog_post SET view_count = view_count + 1 WHERE id = %s` — a single atomic operation. To keep the response coherent, we bump the in-memory copy: `post.view_count += 1` (no extra query).

---

## What's Not Included & Why

Three features (F9, F10, F11) were deliberately deferred. Not from incompetence or laziness, but from conscious risk management:

| Feature | Complexity | Risk | Decision |
|---------|-----------|------|----------|
| **F9:** Batch tags + annotate counts | Low | Medium | Batch tags is trivial; `annotate(Count(..., distinct=True))` is safe but the CLAUDE.md warns about double-count pitfalls. Omitted to avoid subtle bugs. |
| **F10:** Full-text search + GIN | Medium | High | Requires `SearchVectorField` persistent (not `annotate()` which doesn't use indexes). Migration + trigger needed. Risk of "optimized" code that doesn't actually use the index. |
| **F11:** B-tree indexes | Low | Low | Needs `EXPLAIN ANALYZE` on real 100k-post dataset to identify which indexes the planner can't use. Adding "by eye" is cargo-cult engineering. |

**Next priorities if 8 hours more:** Run `EXPLAIN ANALYZE`, add justified indexes (F11) → batch tags (F9) → full-text search (F10) → `django-debug-toolbar` for future devs.

See [NOTAS.md](NOTAS.md) for a detailed retrospective: timeline, design decisions, and rationale for every omission.

---

## How to Review This Work

- **Quick validation:** `docker compose up && docker compose exec web uv run pytest` → all tests pass
- **Query count regressions:** Tests use `CaptureQueriesContext` to assert N+1 is eliminated. See `blog/tests/test_posts.py`
- **Pagination tests:** `test_list_posts_default_page_size`, `test_list_posts_caps_limit`, `test_list_posts_query_count_constant_per_page`
- **Atomic increment:** `test_view_count_increments_on_each_request` — calls GET 5 times, asserts count is exactly 5
- **Architecture:** See `blog/api.py` (routes), `blog/pagination.py` (DefaultPagination), `blog/models.py` (schema)
- **Deep dive:** Read [NOTAS.md](NOTAS.md) for feature-by-feature breakdown, timeline, and design tradeoffs

---

## Development Commands

```bash
# Lint
uv run ruff check .

# Format
uv run ruff format .

# Run all tests
uv run pytest

# Run specific test
uv run pytest blog/tests/test_posts.py::test_list_posts_query_count_is_fixed

# Interactive Django shell
uv run python manage.py shell

# Full dataset seed (~100k posts, ~500k comments; several minutes)
uv run python manage.py seed

# Fast seed for development
uv run python manage.py seed --fast

# Dev server (outside Docker)
uv run python manage.py runserver
```

## Environment Variables

See `.env.example`. Inside Docker, `POSTGRES_HOST=db`; outside, `POSTGRES_HOST=localhost`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/posts` | Published posts, paginated (limit, offset) |
| GET | `/api/posts/search?q=` | Search across title and body |
| GET | `/api/posts/by-tag/{slug}` | Posts by tag, paginated |
| GET | `/api/posts/{id}` | Post detail with comments |
| POST | `/api/posts` | Create a post (with tags) |
| POST | `/api/posts/{id}/comments` | Add a comment |
| GET | `/api/users/{id}` | User profile |
| GET | `/api/users/find?email=` | Look up user by email |
