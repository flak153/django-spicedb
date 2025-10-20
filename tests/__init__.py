"""Test package for django-spicedb."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example_project.settings")

try:
    import django

    django.setup()
except Exception:  # pragma: no cover - bootstrap guard
    # When Django isn't available yet (e.g., during bootstrap), tests that rely
    # on Django will fail explicitly. Basic unit tests that avoid Django can still
    # run without the setup succeeding.
    pass
