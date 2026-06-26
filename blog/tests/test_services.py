import pytest
from django.test import Client

from blog import services
from blog.exceptions import InvalidTagSlugs
from blog.models import Post, Tag, User


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


# --- create_post service ---


@pytest.mark.django_db
def test_create_post_service_attaches_tags(user):
    """Service attaches tags correctly without going through HTTP."""
    Tag.objects.create(name="Python", slug="python")
    Tag.objects.create(name="Django", slug="django")

    post = services.create_post(
        author_id=user.id,
        title="T",
        body="B",
        tag_slugs=["python", "django"],
    )

    assert set(post.tags.values_list("slug", flat=True)) == {"python", "django"}


@pytest.mark.django_db
def test_create_post_service_raises_on_invalid_slug(user):
    """Service raises InvalidTagSlugs (not HttpError) for unknown slugs."""
    with pytest.raises(InvalidTagSlugs):
        services.create_post(
            author_id=user.id,
            title="T",
            body="B",
            tag_slugs=["nonexistent"],
        )


@pytest.mark.django_db
def test_create_post_service_tolerates_duplicate_slugs(user):
    """Duplicate slugs in tag_slugs do not trigger a false InvalidTagSlugs."""
    Tag.objects.create(name="Python", slug="python")

    post = services.create_post(
        author_id=user.id,
        title="T",
        body="B",
        tag_slugs=["python", "python"],
    )

    assert set(post.tags.values_list("slug", flat=True)) == {"python"}


@pytest.mark.django_db
def test_create_post_endpoint_tolerates_duplicate_slugs(client, user):
    """Endpoint returns 200 (not 400) when the same slug appears twice."""
    Tag.objects.create(name="Python", slug="python")

    resp = client.post(
        "/api/posts",
        {"author_id": user.id, "title": "T", "body": "B", "tag_slugs": ["python", "python"]},
        content_type="application/json",
    )

    assert resp.status_code == 200


# --- create_comment service ---


@pytest.mark.django_db
def test_create_comment_service(user):
    """Service creates a comment linked to the correct post and author."""
    post = Post.objects.create(author=user, title="T", body="B")

    comment = services.create_comment(post_id=post.id, author_id=user.id, body="hi")

    assert comment.post_id == post.id
    assert comment.author_id == user.id
    assert comment.body == "hi"


# --- increment_view_count service ---


@pytest.mark.django_db
def test_increment_view_count_service(user):
    """Increments view_count atomically and reflects +1 on the in-memory instance."""
    post = Post.objects.create(author=user, title="T", body="B", view_count=0)

    returned = services.increment_view_count(post)

    assert returned.view_count == 1
    post.refresh_from_db()
    assert post.view_count == 1
