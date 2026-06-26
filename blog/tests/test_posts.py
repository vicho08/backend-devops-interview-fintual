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
    titles = [p["title"] for p in data]
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
