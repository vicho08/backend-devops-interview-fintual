#!/bin/sh
set -e

uv run python manage.py migrate --noinput

exec "$@"
