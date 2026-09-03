"""End-to-end test-client coverage for the Phase 3 refactor:

- upload -> save-mapping -> generate -> download-all returns a real PDF
- /sales-report returns a real PDF (src/sales_report.py extraction)
- /sales-report-export returns the 26-column Thai header row
- `import app` stays clean with FLASK_ENV unset, and raises when
  FLASK_ENV=production without SECRET_KEY (Part D.2 hardening)
"""
import io
import os
import subprocess
import sys

import pytest

import app as app_module
from src.platform_presets import SHOPEE_PRESET

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fixture_bytes(name):
    with open(os.path.join(FIXTURES_DIR, name), 'rb') as f:
        return f.read()


@pytest.fixture
def client():
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as client:
        yield client


def _upload_and_map(client, filename='shopee_sample.csv', platform='shopee'):
    data = {
        'file': (io.BytesIO(_fixture_bytes(filename)), filename),
        'platform': platform,
    }
    resp = client.post('/upload', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200, resp.get_json()

    resp = client.post('/save-mapping', json={'mapping': dict(SHOPEE_PRESET.column_map)})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body['success'] is True
    return body


class TestBillGenerationEndToEnd:
    def test_generate_then_download_all_returns_pdf(self, client):
        _upload_and_map(client)

        resp = client.post('/generate', json={
            'paper_size': 'A5', 'orientation': 'portrait', 'starting_bill_number': '2600001',
        })
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()['success'] is True

        resp = client.get('/download-all')
        assert resp.status_code == 200
        assert resp.data.startswith(b'%PDF')
        assert resp.headers['Content-Type'] == 'application/pdf'


class TestSalesReportEndToEnd:
    def test_sales_report_returns_pdf(self, client):
        _upload_and_map(client)

        resp = client.post('/sales-report', json={'starting_bill_number': '2600001'})
        assert resp.status_code == 200, resp.data
        assert resp.data.startswith(b'%PDF')
        assert resp.headers['Content-Type'] == 'application/pdf'

    def test_sales_report_export_csv_has_thai_header_row(self, client):
        _upload_and_map(client)

        resp = client.post('/sales-report-export', json={
            'format': 'csv', 'starting_bill_number': '2600001',
        })
        assert resp.status_code == 200, resp.data
        text = resp.data.decode('utf-8-sig')
        header_line = text.splitlines()[0]
        assert 'เลขที่บิล' in header_line
        assert 'หมายเลขคำสั่งซื้อ' in header_line
        assert 'จำนวนเงินที่ได้รับจริง' in header_line

    def test_sales_report_without_data_returns_400(self, client):
        # Fresh session, nothing uploaded yet.
        resp = client.post('/sales-report', json={})
        assert resp.status_code == 400
        assert 'error' in resp.get_json()


class TestSecretKeyProductionGuard:
    def _run_import(self, env_overrides):
        env = os.environ.copy()
        env.pop('DATABASE_URL', None)
        env.pop('APP_PASSWORD', None)
        env.pop('SECRET_KEY', None)
        env.pop('FLASK_ENV', None)
        env.update(env_overrides)
        return subprocess.run(
            [sys.executable, '-c', 'import app'],
            cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=30,
        )

    def test_import_app_clean_with_flask_env_unset(self):
        result = self._run_import({})
        assert result.returncode == 0, result.stderr

    def test_production_without_secret_key_raises(self):
        result = self._run_import({'FLASK_ENV': 'production'})
        assert result.returncode != 0
        assert 'SECRET_KEY' in result.stderr

    def test_production_with_secret_key_succeeds(self):
        result = self._run_import({'FLASK_ENV': 'production', 'SECRET_KEY': 'test-secret'})
        assert result.returncode == 0, result.stderr
