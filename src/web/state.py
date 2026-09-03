"""Process-wide, per-browser-session state store shared by every blueprint.

Replaces the old current_invoices/current_csv_path/current_trimmed_df/
current_platform/current_pending_orders module globals, which were
clobbered by concurrent users. Each browser gets a uuid4 'sid' cookie
mapping to its own SessionState in SESSION_STORE (see src/web/helpers.py
for the get_state()/save_state()/get_sid() accessors).
"""
from src.session_state import SessionStore

SESSION_STORE = SessionStore()
