"""End-to-end regression test for the per-session state fix (Part B).

Before this fix, app.py held current_invoices / current_csv_path / etc. as
module-level globals: two concurrent users would clobber each other's
in-progress upload. This test drives the real Flask routes through two
separate test-client instances (each with its own cookie jar, i.e. its own
'sid' session cookie) with interleaved requests, and asserts that user A's
data survives user B's upload untouched — this is the exact bug being fixed,
so it must pass now and would have failed against the old global-state code.
"""
import io
import os

import pytest

import app as app_module
from src.platform_presets import SHOPEE_PRESET, TIKTOK_PRESET

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


def _fixture_bytes(name):
    with open(os.path.join(FIXTURES_DIR, name), 'rb') as f:
        return f.read()


@pytest.fixture
def clients():
    # Two independent test clients, each with its own cookie jar (so each gets
    # its own 'sid' session cookie) — simulating two concurrent browsers.
    # Deliberately not using `with client:` context managers here: nesting two
    # of them for the same Flask app trips over Werkzeug's app-context-stack
    # bookkeeping. Cookie persistence across requests on a single client
    # instance doesn't require the context manager.
    app_module.app.config['TESTING'] = True
    client_a = app_module.app.test_client()
    client_b = app_module.app.test_client()
    return client_a, client_b


def _upload(client, filename, platform):
    data = {
        'file': (io.BytesIO(_fixture_bytes(filename)), filename),
        'platform': platform,
    }
    return client.post('/upload', data=data, content_type='multipart/form-data')


def test_two_interleaved_users_do_not_clobber_each_others_state(clients):
    client_a, client_b = clients

    # User A uploads the Shopee fixture and saves its (platform-default) mapping.
    resp = _upload(client_a, 'shopee_sample.csv', 'shopee')
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True

    resp = client_a.post('/save-mapping', json={'mapping': dict(SHOPEE_PRESET.column_map)})
    assert resp.status_code == 200
    save_a = resp.get_json()
    assert save_a['success'] is True
    assert save_a.get('invoice_count') == 3  # golden: 3 shopee invoices (see tests/test_csv_parser.py)

    # User B uploads the TikTok fixture — interleaved with A's session, using a
    # separate cookie jar (separate 'sid').
    resp = _upload(client_b, 'tiktok_sample.csv', 'tiktok')
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True

    resp = client_b.post('/save-mapping', json={'mapping': dict(TIKTOK_PRESET.column_map)})
    assert resp.status_code == 200
    save_b = resp.get_json()
    assert save_b['success'] is True

    # THE BUG THIS FIXES: under the old module-level globals, B's upload/save-mapping
    # would have overwritten A's current_invoices/current_csv_path/current_platform,
    # so A's /stats and /generate would now reflect TikTok's data instead of Shopee's.
    resp = client_a.get('/stats')
    assert resp.status_code == 200
    assert resp.get_json()['invoice_count'] == 3

    resp = client_a.post('/generate', json={'starting_bill_number': '2600001'})
    assert resp.status_code == 200
    gen_a = resp.get_json()
    assert gen_a['success'] is True
    # generate_batch_bills combines all bills into a single multi-page PDF, so
    # 'count' here is the number of *output files* (1), not invoices.
    assert gen_a['count'] == 1

    # And B's own state must likewise be untouched by A's /generate call above.
    resp = client_b.get('/stats')
    assert resp.status_code == 200
    # tiktok_sample.csv has an unresolved return item needing review, so
    # save-mapping short-circuited before parsing invoices for B — invoice_count
    # stays 0, but crucially it is NOT 3 (A's count), proving isolation.
    assert resp.get_json()['invoice_count'] == 0
