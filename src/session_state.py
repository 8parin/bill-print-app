"""Per-browser-session state, replacing app.py's old module-level globals.

Previously app.py held current_invoices / current_csv_path / current_trimmed_df
/ current_platform / current_pending_orders as module-level globals mutated
via `global` in nearly every route. Two concurrent users would clobber each
other's in-progress upload. SessionState + SessionStore give each browser
session (identified by a uuid4 hex 'sid' cookie) its own isolated state.

Implementation: an in-memory dict for fast access, with a pickle spill to disk
(tempfile.gettempdir()/bill_print_sessions by default, override with the
BILL_PRINT_SESSION_DIR env var) so state survives gunicorn worker restarts on
Render's free tier — a new worker process has an empty in-memory dict but can
still recover a user's state from the spilled pickle on first access.
"""
import os
import pickle
import tempfile
import time
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

DEFAULT_SPILL_DIR = os.path.join(tempfile.gettempdir(), 'bill_print_sessions')
SPILL_DIR = os.environ.get('BILL_PRINT_SESSION_DIR', DEFAULT_SPILL_DIR)
MAX_AGE_SECONDS = 24 * 60 * 60  # prune sessions untouched for ~24h


@dataclass
class SessionState:
    """Everything that used to live in app.py's module-level globals, per user."""

    invoices: list = field(default_factory=list)
    csv_path: Optional[str] = None
    trimmed_df: Optional[pd.DataFrame] = None
    platform: Optional[str] = None
    pending_orders: list = field(default_factory=list)


def _safe_sid(sid: str) -> str:
    """Sanitize a session id before using it as a filename component."""
    return "".join(c for c in str(sid) if c.isalnum()) or "unknown"


class SessionStore:
    """Maps a session id -> SessionState, with an in-memory cache and a disk spill."""

    def __init__(self, spill_dir: str = SPILL_DIR, max_age_seconds: float = MAX_AGE_SECONDS):
        self.spill_dir = spill_dir
        self.max_age_seconds = max_age_seconds
        self._states = {}       # sid -> SessionState
        self._last_access = {}  # sid -> unix timestamp
        try:
            os.makedirs(self.spill_dir, exist_ok=True)
        except Exception as exc:
            print(f"[SessionStore] could not create spill dir {self.spill_dir}: {exc}")

    def _spill_path(self, sid: str) -> str:
        return os.path.join(self.spill_dir, f"{_safe_sid(sid)}.pkl")

    def get(self, sid: str) -> SessionState:
        """Return the SessionState for sid, creating a fresh one if none exists.

        Checks the in-memory cache first, then falls back to the pickle spill
        (e.g. after a worker restart), and finally falls back to a brand new
        SessionState if neither is available or the pickle is corrupt.
        """
        self.prune()
        self._last_access[sid] = time.time()

        if sid in self._states:
            return self._states[sid]

        state = self._load_from_disk(sid)
        if state is None:
            state = SessionState()
        self._states[sid] = state
        return state

    def save(self, sid: str, state: SessionState) -> None:
        """Persist state for sid, both in-memory and spilled to disk."""
        self._states[sid] = state
        self._last_access[sid] = time.time()
        try:
            with open(self._spill_path(sid), 'wb') as f:
                pickle.dump(state, f)
        except Exception as exc:
            print(f"[SessionStore] could not spill session {sid}: {exc}")

    def _load_from_disk(self, sid: str) -> Optional[SessionState]:
        path = self._spill_path(sid)
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'rb') as f:
                state = pickle.load(f)
            if isinstance(state, SessionState):
                return state
            return None
        except Exception as exc:
            print(f"[SessionStore] could not load session {sid} (corrupt or missing): {exc}")
            return None

    def prune(self) -> None:
        """Drop in-memory + on-disk state for sessions untouched for max_age_seconds.

        Prunes both sessions this process has seen (tracked in _last_access)
        and orphaned spill files left behind by other worker processes, using
        each file's mtime as its last-access time.
        """
        now = time.time()

        stale_sids = [sid for sid, ts in self._last_access.items() if now - ts > self.max_age_seconds]
        for sid in stale_sids:
            self._states.pop(sid, None)
            self._last_access.pop(sid, None)
            self._remove_spill(sid)

        try:
            for fname in os.listdir(self.spill_dir):
                if not fname.endswith('.pkl'):
                    continue
                path = os.path.join(self.spill_dir, fname)
                try:
                    if now - os.path.getmtime(path) > self.max_age_seconds:
                        os.remove(path)
                except OSError:
                    continue
        except OSError:
            pass

    def _remove_spill(self, sid: str) -> None:
        path = self._spill_path(sid)
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
