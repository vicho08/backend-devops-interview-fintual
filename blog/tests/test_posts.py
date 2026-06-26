import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from blog.models import Comment, Post, Tag, User


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def user(db):
    return User.objects.create(
        username="alice",
        email="alice@example.com",
        display_name="Alice",
    )


@pytest.mark.django_db
def test_list_posts_returns_published(client, user):
    tag = Tag.objects.create(name="Python", slug="python")
    post = Post.objects.create(author=user, title="Hello", body="World")
    post.tags.add(tag)
    Post.objects.create(author=user, title="Draft", body="...", is_published=False)

    response = client.get("/api/posts")

    assert response.status_code == 200
    data = response.json()
    titles = [p["title"] for p in data["posts"]]
    assert "Hello" in titles
    assert "Draft" not in titles


@pytest.mark.django_db
def test_get_post_returns_detail(client, user):
    post = Post.objects.create(author=user, title="Hello", body="World")

    response = client.get(f"/api/posts/{post.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Hello"
    assert data["author"]["username"] == "alice"
    assert data["comments"] == []


# --- N+1 regression tests ---


@pytest.mark.django_db
def test_list_posts_query_count_is_fixed(client, user):
    tag = Tag.objects.create(name="Python", slug="python")
    for i in range(5):
        p = Post.objects.create(author=user, title=f"Post {i}", body="x")
        p.tags.add(tag)

    with CaptureQueriesContext(connection) as ctx_5:
        client.get("/api/posts")

    # Add 5 more posts and confirm query count doesn't change
    for i in range(5, 10):
        p = Post.objects.create(author=user, title=f"Post {i}", body="x")
        p.tags.add(tag)

    with CaptureQueriesContext(connection) as ctx_10:
        client.get("/api/posts")

    assert len(ctx_5) == len(ctx_10), (
        f"N+1 detected: {len(ctx_5)} queries for 5 posts vs {len(ctx_10)} for 10 posts"
    )


@pytest.mark.django_db
def test_search_posts_query_count_is_fixed(client, user):
    tag = Tag.objects.create(name="Django", slug="django")
    for i in range(5):
        p = Post.objects.create(author=user, title=f"Django tip {i}", body="x")
        p.tags.add(tag)

    with CaptureQueriesContext(connection) as ctx_5:
        client.get("/api/posts/search?q=Django")

    for i in range(5, 10):
        p = Post.objects.create(author=user, title=f"Django tip {i}", body="x")
        p.tags.add(tag)

    with CaptureQueriesContext(connection) as ctx_10:
        client.get("/api/posts/search?q=Django")

    assert len(ctx_5) == len(ctx_10), (
        f"N+1 detected: {len(ctx_5)} queries for 5 posts vs {len(ctx_10)} for 10 posts"
    )


@pytest.mark.django_db
def test_posts_by_tag_query_count_is_fixed(client, user):
    tag = Tag.objects.create(name="Python", slug="python")
    for i in range(5):
        p = Post.objects.create(author=user, title=f"Post {i}", body="x")
        p.tags.add(tag)

    with CaptureQueriesContext(connection) as ctx_5:
        client.get("/api/posts/by-tag/python")

    for i in range(5, 10):
        p = Post.objects.create(author=user, title=f"Post {i}", body="x")
        p.tags.add(tag)

    with CaptureQueriesContext(connection) as ctx_10:
        client.get("/api/posts/by-tag/python")

    assert len(ctx_5) == len(ctx_10), (
        f"N+1 detected: {len(ctx_5)} queries for 5 posts vs {len(ctx_10)} for 10 posts"
    )


# --- Pagination tests ---


@pytest.mark.django_db
def test_list_posts_default_page_size(client, user):
    """Default page_size is 20; creating 25 posts returns 20 items and count=25."""
    for i in range(25):
        Post.objects.create(author=user, title=f"Post {i}", body="x")

    resp = client.get("/api/posts")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["posts"]) == 20
    assert data["count"] == 25


@pytest.mark.django_db
def test_list_posts_caps_limit(client, user):
    """Requesting limit > 100 returns a 422 validation error (server-side cap)."""
    for i in range(110):
        Post.objects.create(author=user, title=f"Post {i}", body="x")

    resp = client.get("/api/posts?limit=1000")

    assert resp.status_code == 422


@pytest.mark.django_db
def test_list_posts_offset_no_overlap(client, user):
    """Second page via offset contains the next set of posts with no overlap."""
    for i in range(25):
        Post.objects.create(author=user, title=f"Post {i}", body="x")

    ids_p1 = {p["id"] for p in client.get("/api/posts?limit=20&offset=0").json()["posts"]}
    ids_p2 = {p["id"] for p in client.get("/api/posts?limit=20&offset=20").json()["posts"]}

    assert len(ids_p1) == 20
    assert len(ids_p2) == 5
    assert ids_p1.isdisjoint(ids_p2)


@pytest.mark.django_db
def test_list_posts_query_count_constant_per_page(client, user):
    """Query count per page is fixed regardless of the total number of posts."""
    tag = Tag.objects.create(name="Python", slug="python")
    for i in range(25):
        p = Post.objects.create(author=user, title=f"Post {i}", body="x")
        p.tags.add(tag)

    with CaptureQueriesContext(connection) as ctx_25:
        client.get("/api/posts?limit=20&offset=0")

    for i in range(25, 225):
        p = Post.objects.create(author=user, title=f"Post {i}", body="x")
        p.tags.add(tag)

    with CaptureQueriesContext(connection) as ctx_225:
        client.get("/api/posts?limit=20&offset=0")

    assert len(ctx_25) == len(ctx_225), (
        f"Query count changed: {len(ctx_25)} for 25 posts vs {len(ctx_225)} for 225"
    )


@pytest.mark.django_db
def test_view_count_increments_on_each_request(client, user):
    """Each GET /posts/{id} increments view_count by exactly 1 (atomic update)."""
    post = Post.objects.create(author=user, title="Test", body="x", view_count=0)

    for _ in range(5):
        client.get(f"/api/posts/{post.id}")

    post.refresh_from_db()
    assert post.view_count == 5


@pytest.mark.django_db
def test_user_detail_counts_are_correct(client, user):
    """post_count and comment_count must be exact, not inflated by cartesian product."""
    other_user = User.objects.create(username="bob", email="bob@example.com", display_name="Bob")
    for i in range(3):
        Post.objects.create(author=user, title=f"Post {i}", body="x")
    for i in range(2):
        post = Post.objects.create(author=other_user, title=f"Other {i}", body="x")
        Comment.objects.create(post=post, author=user, body="comment")

    resp = client.get(f"/api/users/{user.id}")
    data = resp.json()

    assert data["post_count"] == 3  # NOT 6 (3×2 cartesian product)
    assert data["comment_count"] == 2  # NOT 6 (3×2 cartesian product)


@pytest.mark.django_db
def test_create_post_assigns_all_tags(client, user):
    """All requested tag slugs are attached via a single batch lookup."""
    Tag.objects.create(name="Python", slug="python")
    Tag.objects.create(name="Django", slug="django")

    resp = client.post(
        "/api/posts",
        {"author_id": user.id, "title": "T", "body": "B", "tag_slugs": ["python", "django"]},
        content_type="application/json",
    )

    assert resp.status_code == 200
    post = Post.objects.get(id=resp.json()["id"])
    assert set(post.tags.values_list("slug", flat=True)) == {"python", "django"}


@pytest.mark.django_db
def test_create_post_invalid_tag_slug_returns_400(client, user):
    """A nonexistent tag slug returns 400 instead of crashing with 500."""
    resp = client.post(
        "/api/posts",
        {"author_id": user.id, "title": "T", "body": "B", "tag_slugs": ["nonexistent"]},
        content_type="application/json",
    )

    assert resp.status_code == 400


@pytest.mark.django_db
def test_get_post_query_count_is_fixed(client, user):
    def make_post_with_comments(title, n_comments):
        post = Post.objects.create(author=user, title=title, body="body")
        for i in range(n_comments):
            commenter = User.objects.create(
                username=f"commenter_{title}_{i}",
                email=f"c_{title}_{i}@x.com",
                display_name=f"C{i}",
            )
            Comment.objects.create(post=post, author=commenter, body=f"Comment {i}")
        return post

    post_small = make_post_with_comments("small", 3)
    post_large = make_post_with_comments("large", 20)

    with CaptureQueriesContext(connection) as ctx_small:
        client.get(f"/api/posts/{post_small.id}")

    with CaptureQueriesContext(connection) as ctx_large:
        client.get(f"/api/posts/{post_large.id}")

    assert len(ctx_small) == len(ctx_large), (
        f"N+1 detected: {len(ctx_small)} queries for 3 comments vs {len(ctx_large)} for 20 comments"
    )
