from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.pagination import paginate

from blog import selectors, services
from blog.models import Tag
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
    return post


@router.post("/posts", response=PostCreateOut)
def create_post(request, payload: PostCreateIn):
    post = services.create_post(
        author_id=payload.author_id,
        title=payload.title,
        body=payload.body,
        tag_slugs=payload.tag_slugs,
    )
    return post


@router.post("/posts/{post_id}/comments", response=CommentCreateOut)
def create_comment(request, post_id: int, payload: CommentCreateIn):
    comment = services.create_comment(
        post_id=post_id,
        author_id=payload.author_id,
        body=payload.body,
    )
    return comment


@router.get("/users/find", response=UserDetailOut)
def find_user_by_email(request, email: str):
    return get_object_or_404(selectors.annotated_users(), email=email)


@router.get("/users/{user_id}", response=UserDetailOut)
def get_user(request, user_id: int):
    return get_object_or_404(selectors.annotated_users(), id=user_id)
