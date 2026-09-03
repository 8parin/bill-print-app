"""Tests for app.py: bill number parsing helpers and a Flask smoke test.

conftest.py unsets DATABASE_URL and APP_PASSWORD before this module is
imported, so `import app` never touches a real database and never gates
routes behind a login screen.
"""
import pytest

import app as app_module


class TestParseBillNumber:
    def test_plain_numeric(self):
        assert app_module.parse_bill_number('2600001') == ('', 2600001)

    def test_prefixed(self):
        assert app_module.parse_bill_number('LZ26000015') == ('LZ', 26000015)

    def test_prefixed_tiktok(self):
        assert app_module.parse_bill_number('TT26000015') == ('TT', 26000015)

    def test_non_numeric_fallback(self):
        assert app_module.parse_bill_number('abc') == ('abc', 0)

    def test_strips_whitespace(self):
        assert app_module.parse_bill_number('  2600001  ') == ('', 2600001)


class TestFormatBillNumber:
    def test_no_prefix(self):
        assert app_module.format_bill_number('', 2600001) == '2600001'

    def test_with_prefix(self):
        assert app_module.format_bill_number('LZ', 26000015) == 'LZ26000015'

    def test_roundtrip_with_parse(self):
        prefix, number = app_module.parse_bill_number('LZ26000015')
        assert app_module.format_bill_number(prefix, number) == 'LZ26000015'


class TestFlaskSmoke:
    @pytest.fixture
    def client(self):
        app_module.app.config['TESTING'] = True
        with app_module.app.test_client() as client:
            yield client

    def test_index_returns_200(self, client):
        # APP_PASSWORD is unset (see conftest.py), so login_required lets this
        # through without a session.
        resp = client.get('/')
        assert resp.status_code == 200


class TestGenericErrorHandling:
    """Phase 3 hardening: routes must no longer leak raw exception strings on
    500s. They should log the traceback (app.logger.exception) and return a
    generic, non-leaking message instead."""

    @pytest.fixture
    def client(self):
        app_module.app.config['TESTING'] = True
        with app_module.app.test_client() as client:
            yield client

    def test_save_mapping_500_returns_generic_message(self, client, monkeypatch):
        secret_detail = "super secret internal detail: /etc/passwd traceback line 42"

        def _boom(*args, **kwargs):
            raise RuntimeError(secret_detail)

        # _make_parser() runs inside save_mapping()'s try block, right after
        # request validation — a clean way to force the except branch.
        monkeypatch.setattr(app_module, '_make_parser', _boom)

        resp = client.post('/save-mapping', json={'mapping': {}})

        assert resp.status_code == 500
        data = resp.get_json()
        assert 'error' in data
        # The raw exception text must never reach the client.
        assert secret_detail not in data['error']
        assert data['error'] == 'Internal error while saving the column mapping. Check server logs.'
