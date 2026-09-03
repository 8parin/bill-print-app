"""Shared app configuration store.

config.json is loaded once, into this module, at import time. Every
blueprint imports the same `config` dict object from here (not a copy), so
a mutation made by one route (e.g. /save-company) is immediately visible to
every other route (e.g. get_company_info() used by /generate).
"""
import json

CONFIG_PATH = 'config.json'

with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = json.load(f)


def save_config():
    """Persist the current in-memory config dict back to config.json.

    config.json is a local-fallback persistence mechanism only; callers
    decide when a write is actually needed (e.g. skipped when a DB profile
    save already handled persistence).
    """
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
