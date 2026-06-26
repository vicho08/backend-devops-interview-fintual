from django.db.models import F
from django.shortcuts import get_object_or_404

from blog.exceptions import InvalidTagSlugs
from blog.models import Comment, Post, Tag, User


def create_post(*, author_id: int, title: str, body: str, tag_slugs: list[str]) -> Post:
    """Create and return a Post with the given tags attached.

    Uses get_object_or_404 for the author lookup (Django translates a missing
    User to a 404 at the HTTP boundary — acceptable coupling for this project).
    Raises InvalidTagSlugs if any slug in tag_slugs does not exist.
    Deduplicates tag_slugs via set() before comparing counts to avoid false
    negatives when the caller sends the same slug more than once.
    """
    author = get_object_or_404(User, id=author_id)
    post = Post.objects.create(author=author, title=title, body=body)
    tags = Tag.objects.filter(slug__in=tag_slugs)
    if len(tags) != len(set(tag_slugs)):
        raise InvalidTagSlugs()
    post.tags.set(tags)
    return post


def create_comment(*, post_id: int, author_id: int, body: str) -> Comment:
    """Create and return a Comment on the given post by the given author."""
    post = get_object_or_404(Post, id=post_id)
    author = get_object_or_404(User, id=author_id)
    return Comment.objects.create(post=post, author=author, body=body)


def increment_view_count(post: Post) -> Post:
    """Atomically increment view_count and reflect the +1 on the in-memory instance.

    The UPDATE is issued at the database level (no read-modify-write race condition).
    The in-memory bump avoids a follow-up SELECT to keep the response coherent.
    """
    Post.objects.filter(id=post.id).update(view_count=F("view_count") + 1)
    post.view_count += 1
    return post
