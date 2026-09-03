"""Tests for src/session_state.py: per-browser-session state storage.

Covers the concurrency-bug fix directly — two sids must never see each
other's data — plus the pickle spill/reload path that keeps state alive
across a gunicorn worker restart on Render's free tier, and pruning of
stale sessions.
"""
import os
import time

import pandas as pd
import pytest

from src.session_state import SessionState, SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(spill_dir=str(tmp_path), max_age_seconds=3600)


class TestBasicRoundtrip:
    def test_get_creates_fresh_state(self, store):
        state = store.get('sid-a')
        assert isinstance(state, SessionState)
        assert state.invoices == []
        assert state.csv_path is None
        assert state.trimmed_df is None
        assert state.platform is None
        assert state.pending_orders == []

    def test_save_then_get_returns_same_data(self, store):
        state = store.get('sid-a')
        state.csv_path = '/tmp/foo.csv'
        state.platform = 'shopee'
        state.invoices = ['inv1', 'inv2']
        store.save('sid-a', state)

        reloaded = store.get('sid-a')
        assert reloaded.csv_path == '/tmp/foo.csv'
        assert reloaded.platform == 'shopee'
        assert reloaded.invoices == ['inv1', 'inv2']


class TestIsolationBetweenSessions:
    def test_two_sids_never_see_each_others_state(self, store):
        state_a = store.get('sid-a')
        state_a.platform = 'shopee'
        state_a.invoices = ['a1', 'a2', 'a3']
        store.save('sid-a', state_a)

        state_b = store.get('sid-b')
        state_b.platform = 'tiktok'
        state_b.invoices = ['b1']
        store.save('sid-b', state_b)

        reloaded_a = store.get('sid-a')
        reloaded_b = store.get('sid-b')

        assert reloaded_a.platform == 'shopee'
        assert len(reloaded_a.invoices) == 3
        assert reloaded_b.platform == 'tiktok'
        assert len(reloaded_b.invoices) == 1


class TestPickleSpillAndReload:
    def test_save_writes_a_pickle_file(self, store, tmp_path):
        state = store.get('sid-c')
        state.platform = 'lazada'
        store.save('sid-c', state)

        files = os.listdir(tmp_path)
        assert any(f.endswith('.pkl') for f in files)

    def test_reload_from_disk_after_memory_is_cleared(self, tmp_path):
        # Simulate a gunicorn worker restart: state saved by one store
        # instance must be recoverable by a brand new instance pointed at the
        # same spill dir, with no in-memory cache carried over.
        store1 = SessionStore(spill_dir=str(tmp_path), max_age_seconds=3600)
        state = store1.get('sid-d')
        state.platform = 'shopee'
        state.csv_path = '/tmp/bar.csv'
        state.trimmed_df = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
        store1.save('sid-d', state)

        store2 = SessionStore(spill_dir=str(tmp_path), max_age_seconds=3600)
        reloaded = store2.get('sid-d')
        assert reloaded.platform == 'shopee'
        assert reloaded.csv_path == '/tmp/bar.csv'
        assert reloaded.trimmed_df is not None
        assert list(reloaded.trimmed_df['a']) == [1, 2]

    def test_corrupt_pickle_falls_back_to_fresh_state(self, tmp_path):
        store = SessionStore(spill_dir=str(tmp_path), max_age_seconds=3600)
        # Write garbage where a real pickle would go.
        path = store._spill_path('sid-e')
        with open(path, 'wb') as f:
            f.write(b'not a real pickle')

        state = store.get('sid-e')
        assert isinstance(state, SessionState)
        assert state.invoices == []

    def test_missing_pickle_falls_back_to_fresh_state(self, store):
        state = store.get('sid-never-saved')
        assert isinstance(state, SessionState)


class TestPruning:
    def test_prune_drops_stale_in_memory_and_disk_entries(self, store, tmp_path):
        state = store.get('sid-old')
        store.save('sid-old', state)

        # Backdate this session's last-access time and its spill file's mtime
        # well past max_age_seconds so prune() treats it as stale.
        old_ts = time.time() - 100000
        store._last_access['sid-old'] = old_ts
        spill_path = store._spill_path('sid-old')
        os.utime(spill_path, (old_ts, old_ts))

        store.prune()

        assert 'sid-old' not in store._states
        assert 'sid-old' not in store._last_access
        assert not os.path.exists(spill_path)

    def test_prune_leaves_fresh_entries_alone(self, store):
        state = store.get('sid-fresh')
        store.save('sid-fresh', state)

        store.prune()

        assert 'sid-fresh' in store._states
        assert os.path.exists(store._spill_path('sid-fresh'))

    def test_prune_removes_orphaned_spill_files_from_other_processes(self, store, tmp_path):
        # A file left behind by a worker process that no longer exists in
        # this store's in-memory _last_access dict should still be pruned by
        # mtime.
        orphan_path = os.path.join(str(tmp_path), 'orphansid.pkl')
        with open(orphan_path, 'wb') as f:
            f.write(b'irrelevant')
        old_ts = time.time() - 100000
        os.utime(orphan_path, (old_ts, old_ts))

        store.prune()

        assert not os.path.exists(orphan_path)
