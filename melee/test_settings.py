"""Test-only settings.

This project's schema was hand-built / inspectdb-generated, so the `main`
migration chain can't construct the database from scratch (a fresh test DB
fails with "relation \"player\" does not exist"). For tests we therefore:

  * use an in-memory SQLite database (never touches the real Postgres), and
  * disable `main`'s migrations so Django builds the schema directly from the
    current model definitions (managed models only — TournamentResults is
    managed=False and intentionally has no table; no test depends on it).

Run with:  python manage.py test --settings=melee.test_settings
"""
from melee.settings import *  # noqa: F401,F403


class _DisableMainMigrations:
    def __contains__(self, item):
        return item == 'main'

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = _DisableMainMigrations()

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Fast, deterministic cache isolated per process for the caching tests.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'melee-test',
    }
}

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
