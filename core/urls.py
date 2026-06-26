from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI

from blog.api import router as blog_router
from blog.exceptions import DomainError

api = NinjaAPI()
api.add_router("/", blog_router)


@api.exception_handler(DomainError)
def handle_domain_error(request, exc):
    return api.create_response(request, {"detail": str(exc)}, status=400)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
