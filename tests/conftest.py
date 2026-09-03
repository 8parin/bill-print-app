"""Shared pytest fixtures / setup for the Bill Print test suite.

Ensures the project root is importable (so `import app` and `from src...`
work regardless of the invocation directory) and that tests never touch a
real database or require a login password.
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# app.py reads these at import time (module-level globals). Force them unset
# so importing app.py never tries to hit a real Postgres database and never
# gates routes behind a login screen during tests.
os.environ.pop('DATABASE_URL', None)
os.environ.pop('APP_PASSWORD', None)

# app.py opens 'config.json' with a relative path, so tests must run with the
# project root as the working directory. Guarantee that regardless of how
# pytest was invoked (e.g. `pytest tests/` from elsewhere).
os.chdir(PROJECT_ROOT)

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
CONFIG_PATH = os.path.join(PROJECT_ROOT, 'config.json')


import pytest


@pytest.fixture(autouse=True)
def _restore_config_json():
    # Several routes (/save-mapping, /save-company, /api/company-profiles/...)
    # persist to config.json. Save/restore the real project config.json around
    # every test so driving these routes through the Flask test client never
    # leaves the repo's config.json permanently mutated.
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        original = f.read()
    try:
        yield
    finally:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            f.write(original)
