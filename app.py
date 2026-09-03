"""
Bill Print Flask Application

Thin entry point: creates the Flask app, wires up config/paths/DB, and
registers the feature blueprints under src/web/routes/. The actual route
handlers and their shared helpers live in src/web/ (see helpers.py,
config_store.py, state.py and routes/*.py).

Render runs `gunicorn app:app`, so this module must keep exposing a
module-level `app` object.
"""
import os

from flask import Flask

app = Flask(__name__)

# On Render (FLASK_ENV=production), sessions/sid cookies MUST survive process
# restarts (gunicorn worker recycling, redeploys). A random os.urandom() key
# generated at import time would invalidate every session on every restart,
# so production requires an explicit SECRET_KEY env var. Local/dev keeps the
# os.urandom() fallback for convenience.
if os.environ.get('FLASK_ENV') == 'production' and not os.environ.get('SECRET_KEY'):
    raise RuntimeError(
        "SECRET_KEY environment variable is required when FLASK_ENV=production "
        "(sessions/sid cookies would break on every restart otherwise). "
        "Set SECRET_KEY in the Render dashboard, or in render.yaml with generateValue: true."
    )
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

from src.web.config_store import config  # noqa: E402  (after secret-key guard, before use below)

# Re-exported for backwards compatibility: tests import these off `app`
# (e.g. tests/test_app.py monkeypatches app._make_parser to verify routes
# don't leak raw exception text), and the blueprints under src/web/routes/
# look several of these up dynamically via `import app` so such monkeypatches
# reach them exactly as they did when everything lived in this one module.
from src.web.helpers import (  # noqa: E402,F401
    login_required, parse_bill_number, format_bill_number, _assign_bill_numbers,
    get_sid, get_state, save_state, _get_platform_preset, _make_parser,
    get_company_info, _build_invoice_lookup, APP_PASSWORD,
)


def _db_available():
    """Check if DATABASE_URL is set"""
    return bool(os.environ.get('DATABASE_URL'))


# Initialize database if available
if _db_available():
    try:
        from src.database import init_database, get_all_profiles, get_profile, save_profile, delete_profile
        init_database()
        print("[DB] Database initialized successfully")
    except Exception as e:
        print(f"[DB] Database init failed, falling back to config.json: {e}")

# Configuration - use absolute paths to avoid issues with send_file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, config['settings']['upload_folder'].lstrip('./'))
app.config['OUTPUT_FOLDER'] = os.path.join(BASE_DIR, config['settings']['output_folder'].lstrip('./'))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Ensure directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

from src.web.routes.auth import auth_bp
from src.web.routes.uploads import uploads_bp
from src.web.routes.bills import bills_bp
from src.web.routes.profiles import profiles_bp
from src.web.routes.reports import reports_bp

app.register_blueprint(auth_bp)
app.register_blueprint(uploads_bp)
app.register_blueprint(bills_bp)
app.register_blueprint(profiles_bp)
app.register_blueprint(reports_bp)


if __name__ == '__main__':
    # Auto-open browser
    import webbrowser
    import threading

    # Only open browser on first run, not on reloader restarts
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        def open_browser():
            webbrowser.open('http://localhost:5003')
        threading.Timer(1.5, open_browser).start()

    # Run Flask
    app.run(debug=True, port=5003, host='0.0.0.0')
