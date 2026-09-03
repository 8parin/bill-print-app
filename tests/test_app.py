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
