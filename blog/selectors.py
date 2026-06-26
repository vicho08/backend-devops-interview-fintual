from django.db.models import Count, Prefetch, Q, QuerySet

from blog.models import Comment, Post, User


def published_posts() -> QuerySet[Post]:
    """Return published posts with author and tags eagerly loaded, newest first."""
    return (
        Post.objects.filter(is_published=True)
        .select_related("author")
        .prefetch_related("tags")
        .order_by("-created_at")
    )


def search_published_posts(q: str) -> QuerySet[Post]:
    """Return published posts whose title or body contains q (case-insensitive).

    NOTE: Uses icontains (sequential scan). Full-text search with GIN index is F10.
    """
    return published_posts().filter(Q(title__icontains=q) | Q(body__icontains=q))


def posts_for_tag(slug: str) -> QuerySet[Post]:
    """Return published posts that carry the given tag slug.

    The caller is responsible for validating that the tag exists (e.g. via
    get_object_or_404) before calling this selector. A nonexistent slug produces
    an empty queryset, not a 404 — that HTTP concern belongs in the view layer.
    """
    return published_posts().filter(tags__slug=slug)


def post_detail_qs() -> QuerySet[Post]:
    """Return a Post queryset with full eager loading for the detail endpoint.

    Loads author, tags, and comments (with their authors, ordered by created_at)
    in a fixed number of queries regardless of comment count.
    The named Prefetch preserves the ordering at the database level.
    """
    return Post.objects.select_related("author").prefetch_related(
        "tags",
        Prefetch(
            "comments",
            queryset=Comment.objects.select_related("author").order_by("created_at"),
        ),
    )


def annotated_users() -> QuerySet[User]:
    """Return a User queryset with post_count and comment_count annotated.

    Uses distinct=True on both counts to avoid the cartesian product from joining
    two multi-valued relations simultaneously. Without distinct, a user with P posts
    and C comments would report P*C for both counts instead of P and C.
    """
    return User.objects.annotate(
        post_count=Count("posts", distinct=True),
        comment_count=Count("comments", distinct=True),
    )
