from datetime import datetime

from ninja import Schema


class AuthorOut(Schema):
    id: int
    username: str
    display_name: str


class TagOut(Schema):
    id: int
    name: str
    slug: str


class PostListOut(Schema):
    id: int
    title: str
    author: AuthorOut
    tags: list[TagOut]
    view_count: int
    created_at: datetime

    @staticmethod
    def resolve_tags(obj):
        return obj.tags.all()


class CommentOut(Schema):
    id: int
    author: AuthorOut
    body: str
    created_at: datetime


class PostDetailOut(Schema):
    id: int
    title: str
    body: str
    author: AuthorOut
    tags: list[TagOut]
    comments: list[CommentOut]
    view_count: int
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_tags(obj):
        return obj.tags.all()

    @staticmethod
    def resolve_comments(obj):
        # Uses .all() to reuse the ordered Prefetch cache from post_detail_qs().
        # DO NOT add .order_by() here — it would bypass the prefetch and re-query.
        return obj.comments.all()


class UserDetailOut(Schema):
    id: int
    username: str
    display_name: str
    email: str
    bio: str
    post_count: int
    comment_count: int


class PostCreateIn(Schema):
    author_id: int
    title: str
    body: str
    tag_slugs: list[str] = []


class PostCreateOut(Schema):
    id: int
    title: str


class CommentCreateIn(Schema):
    author_id: int
    body: str


class CommentCreateOut(Schema):
    id: int
