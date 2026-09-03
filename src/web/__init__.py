"""Flask web layer: app-shared state (config, session store) and blueprints.

app.py stays a thin entry point; the actual routes live under
src/web/routes/, and the helpers/singletons they share live in
src/web/helpers.py, src/web/config_store.py and src/web/state.py.
"""
