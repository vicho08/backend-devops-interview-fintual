from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.pagination import paginate

from blog import selectors, services
from blog.models import Tag, User
from blog.pagination import DefaultPagination
from blog.schemas import (
    CommentCreateIn,
    CommentCreateOut,
    PostCreateIn,
    PostCreateOut,
    PostDetailOut,
    PostListOut,
    UserDetailOut,
)

router = Router()


def _serialize_author(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
    }


def _serialize_tag(tag: Tag) -> dict:
    return {"id": tag.id, "name": tag.name, "slug": tag.slug}


@router.get("/posts", response=list[PostListOut])
@paginate(DefaultPagination)
def list_posts(request):
    """Return published posts ordered by creation date, newest first."""
    return selectors.published_posts()


@router.get("/posts/search", response=list[PostListOut])
@paginate(DefaultPagination)
def search_posts(request, q: str):
    """Return published posts whose title or body contains the query string."""
    return selectors.search_published_posts(q)


@router.get("/posts/by-tag/{slug}", response=list[PostListOut])
@paginate(DefaultPagination)
def posts_by_tag(request, slug: str):
    """Return published posts that have the given tag slug.

    Returns 404 if the tag slug does not exist, preserving the original contract.
    An existing tag with no published posts returns an empty list.
    """
    get_object_or_404(Tag, slug=slug)
    return selectors.posts_for_tag(slug)


@router.get("/posts/{post_id}", response=PostDetailOut)
def get_post(request, post_id: int):
    post = get_object_or_404(selectors.post_detail_qs(), id=post_id)
    services.increment_view_count(post)

    comments = [
        {
            "id": c.id,
            "author": _serialize_author(c.author),
            "body": c.body,
            "created_at": c.created_at,
        }
        for c in post.comments.all()
    ]
    return {
        "id": post.id,
        "title": post.title,
        "body": post.body,
        "author": _serialize_author(post.author),
        "tags": [_serialize_tag(t) for t in post.tags.all()],
        "comments": comments,
        "view_count": post.view_count,
        "created_at": post.created_at,
        "updated_at": post.updated_at,
    }


@router.post("/posts", response=PostCreateOut)
def create_post(request, payload: PostCreateIn):
    post = services.create_post(
        author_id=payload.author_id,
        title=payload.title,
        body=payload.body,
        tag_slugs=payload.tag_slugs,
    )
    return {"id": post.id, "title": post.title}


@router.post("/posts/{post_id}/comments", response=CommentCreateOut)
def create_comment(request, post_id: int, payload: CommentCreateIn):
    comment = services.create_comment(
        post_id=post_id,
        author_id=payload.author_id,
        body=payload.body,
    )
    return {"id": comment.id}


@router.get("/users/find", response=UserDetailOut)
def find_user_by_email(request, email: str):
    user = get_object_or_404(selectors.annotated_users(), email=email)
    return _user_detail(user)


@router.get("/users/{user_id}", response=UserDetailOut)
def get_user(request, user_id: int):
    user = get_object_or_404(selectors.annotated_users(), id=user_id)
    return _user_detail(user)


def _user_detail(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "bio": user.bio,
        "post_count": user.post_count,
        "comment_count": user.comment_count,
    }
