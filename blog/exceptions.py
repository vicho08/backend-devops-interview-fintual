class DomainError(Exception):
    """Base for business-rule errors. The message is safe to expose to the client."""


class InvalidTagSlugs(DomainError):
    def __init__(self, message="One or more tag slugs do not exist."):
        super().__init__(message)
