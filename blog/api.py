from django.db.models import Count, F, Prefetch, Q
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError
from ninja.pagination import paginate

from blog.models import Comment, Post, Tag, User
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
    return (
        Post.objects.filter(is_published=True)
        .select_related("author")
        .prefetch_related("tags")
        .order_by("-created_at")
    )


@router.get("/posts/search", response=list[PostListOut])
@paginate(DefaultPagination)
def search_posts(request, q: str):
    """Return published posts whose title or body contains the query string."""
    return (
        Post.objects.filter(
            Q(title__icontains=q) | Q(body__icontains=q),
            is_published=True,
        )
        .select_related("author")
        .prefetch_related("tags")
        .order_by("-created_at")
    )


@router.get("/posts/by-tag/{slug}", response=list[PostListOut])
@paginate(DefaultPagination)
def posts_by_tag(request, slug: str):
    """Return published posts that have the given tag slug."""
    tag = get_object_or_404(Tag, slug=slug)
    return (
        tag.posts.filter(is_published=True)
        .select_related("author")
        .prefetch_related("tags")
        .order_by("-created_at")
    )


@router.get("/posts/{post_id}", response=PostDetailOut)
def get_post(request, post_id: int):
    post = get_object_or_404(
        Post.objects.select_related("author").prefetch_related(
            "tags",
            Prefetch(
                "comments",
                queryset=Comment.objects.select_related("author").order_by("created_at"),
            ),
        ),
        id=post_id,
    )
    Post.objects.filter(id=post_id).update(view_count=F("view_count") + 1)
    post.view_count += 1

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
    author = get_object_or_404(User, id=payload.author_id)
    post = Post.objects.create(
        author=author,
        title=payload.title,
        body=payload.body,
    )
    tags = Tag.objects.filter(slug__in=payload.tag_slugs)
    if len(tags) != len(payload.tag_slugs):
        raise HttpError(400, "One or more tag slugs do not exist.")
    post.tags.set(tags)
    return {"id": post.id, "title": post.title}


@router.post("/posts/{post_id}/comments", response=CommentCreateOut)
def create_comment(request, post_id: int, payload: CommentCreateIn):
    post = get_object_or_404(Post, id=post_id)
    author = get_object_or_404(User, id=payload.author_id)
    comment = Comment.objects.create(post=post, author=author, body=payload.body)
    return {"id": comment.id}


def _annotated_user_qs():
    """Return a User queryset with post_count and comment_count annotated in a single query.

    Uses distinct=True on both counts to avoid the cartesian product that arises
    when joining two multi-valued relations (posts and comments) simultaneously.
    Without distinct, a user with P posts and C comments would report P*C for both counts.
    """
    return User.objects.annotate(
        post_count=Count("posts", distinct=True),
        comment_count=Count("comments", distinct=True),
    )


@router.get("/users/find", response=UserDetailOut)
def find_user_by_email(request, email: str):
    user = get_object_or_404(_annotated_user_qs(), email=email)
    return _user_detail(user)


@router.get("/users/{user_id}", response=UserDetailOut)
def get_user(request, user_id: int):
    user = get_object_or_404(_annotated_user_qs(), id=user_id)
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
