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


class TestRouteMap:
    """Phase 4 refactor: app.py was split into Flask blueprints
    (src/web/routes/*.py). This asserts every pre-existing route still
    resolves to the exact same (method, path) pair — i.e. the blueprint
    split didn't change any URL, drop a route, or add a url_prefix."""

    # (HTTP method, URL path) pairs that existed as plain @app.route(...)
    # endpoints before the blueprint split.
    EXPECTED_ROUTES = [
        ('GET', '/login'),
        ('POST', '/login'),
        ('GET', '/logout'),
        ('GET', '/'),
        ('POST', '/upload'),
        ('POST', '/save-company'),
        ('GET', '/api/company-profiles'),
        ('POST', '/api/company-profiles/select/<profile_name>'),
        ('DELETE', '/api/company-profiles/<profile_name>'),
        ('GET', '/get-field-definitions'),
        ('POST', '/set-platform'),
        ('POST', '/save-mapping'),
        ('POST', '/apply-return-decisions'),
        ('GET', '/preview'),
        ('POST', '/preview-by-order'),
        ('POST', '/generate'),
        ('GET', '/debug-bills'),
        ('POST', '/generate-one'),
        ('POST', '/generate-by-order'),
        ('GET', '/download/<filename>'),
        ('GET', '/download-all'),
        ('POST', '/sales-report'),
        ('POST', '/sales-report-export'),
        ('POST', '/sort-csv'),
        ('GET', '/stats'),
        ('GET', '/version'),
    ]

    def test_all_pre_existing_routes_resolve(self):
        url_map_entries = {
            (method, rule.rule)
            for rule in app_module.app.url_map.iter_rules()
            for method in rule.methods
            if method not in ('HEAD', 'OPTIONS')
        }
        for method, path in self.EXPECTED_ROUTES:
            assert (method, path) in url_map_entries, f'missing route: {method} {path}'
