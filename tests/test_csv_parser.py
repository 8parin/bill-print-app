"""Regression / golden tests for src/csv_parser.py against real sample exports.

These pin ACTUAL current behavior (observed by running the parser against the
fixtures) rather than "expected" behavior, so they catch accidental changes
during the upcoming pipeline refactor. If a value here needs to change, it
should be because the parsing logic intentionally changed — re-derive the
golden value from the fixture, don't just make the test pass.
"""
import os

import pytest

from src.csv_parser import CSVParser
from src.platform_presets import SHOPEE_PRESET, LAZADA_PRESET, TIKTOK_PRESET

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


def _fixture(name):
    return os.path.join(FIXTURES_DIR, name)


@pytest.fixture
def shopee_parser():
    return CSVParser(platform=SHOPEE_PRESET)


@pytest.fixture
def lazada_parser():
    return CSVParser(platform=LAZADA_PRESET)


@pytest.fixture
def tiktok_parser():
    return CSVParser(platform=TIKTOK_PRESET)


def _pipeline(parser, path):
    """Run the same steps parse_csv_to_invoices does, returning intermediate
    counts plus the final invoice dict (keyed by invoice number, insertion
    order = sort order)."""
    df = parser.read_csv(path)
    raw_shape = df.shape
    df, cancelled_count = parser.filter_cancelled_invoices(df)
    df, preorder_count = parser.filter_preorders(df)
    df, confirmed_return_count = parser.filter_confirmed_returns(df)
    grouped = parser.group_by_invoice(df)
    invoices = {k: parser.parse_invoice(g, k) for k, g in grouped.items()}
    return {
        'raw_shape': raw_shape,
        'cancelled_count': cancelled_count,
        'preorder_count': preorder_count,
        'confirmed_return_count': confirmed_return_count,
        'invoices': invoices,
    }


class TestShopee:
    def test_read_csv_shape(self, shopee_parser):
        df = shopee_parser.read_csv(_fixture('shopee_sample.csv'))
        assert df.shape == (12, 59)

    def test_pipeline_counts_and_order(self, shopee_parser):
        result = _pipeline(shopee_parser, _fixture('shopee_sample.csv'))
        assert result['cancelled_count'] == 1
        assert result['preorder_count'] == 0
        assert result['confirmed_return_count'] == 0
        assert len(result['invoices']) == 3
        # order_sort_key ascending == group_by_invoice's insertion (chronological) order
        assert list(result['invoices'].keys()) == [
            '260203QN0QGY27', '260211EB9UDEBD', '260221AYM6EYHF',
        ]

    def test_invoice_totals(self, shopee_parser):
        result = _pipeline(shopee_parser, _fixture('shopee_sample.csv'))
        inv = result['invoices']['260203QN0QGY27']
        assert inv.grand_total == 264.0
        assert inv.vat_amount == 17.27
        assert inv.total_before_vat == 246.73
        assert len(inv.items) == 1
        assert inv.order_sort_key == '2026-02-04 09:59:00'

        inv2 = result['invoices']['260211EB9UDEBD']
        assert inv2.grand_total == 445.0
        assert len(inv2.items) == 5

    def test_sum_of_grand_totals(self, shopee_parser):
        result = _pipeline(shopee_parser, _fixture('shopee_sample.csv'))
        total = sum(inv.grand_total for inv in result['invoices'].values())
        assert round(total, 2) == 1374.0


class TestLazada:
    def test_read_csv_shape(self, lazada_parser):
        df = lazada_parser.read_csv(_fixture('lazada_sample.csv'))
        assert df.shape == (127, 76)

    def test_pipeline_counts_and_order(self, lazada_parser):
        result = _pipeline(lazada_parser, _fixture('lazada_sample.csv'))
        assert result['cancelled_count'] == 16
        assert result['preorder_count'] == 0
        assert result['confirmed_return_count'] == 0
        assert len(result['invoices']) == 92
        assert list(result['invoices'].keys())[:5] == [
            '1072461471301325', '1080505124492448', '1072519667724528',
            '1080526782286012', '1072570650860182',
        ]

    def test_invoice_totals(self, lazada_parser):
        result = _pipeline(lazada_parser, _fixture('lazada_sample.csv'))
        inv = result['invoices']['1072461471301325']
        assert inv.grand_total == 208.5
        assert inv.vat_amount == 13.64
        assert inv.total_before_vat == 194.86
        assert inv.order_sort_key == '2026-02-02 09:09:00'

    def test_sum_of_grand_totals(self, lazada_parser):
        result = _pipeline(lazada_parser, _fixture('lazada_sample.csv'))
        total = sum(inv.grand_total for inv in result['invoices'].values())
        assert round(total, 2) == 27045.26


class TestTiktok:
    def test_read_csv_shape_drops_description_row(self, tiktok_parser):
        # File has 37 data rows + header; skip_rows=[0] drops the metadata
        # row that some TikTok exports include right after the header.
        df = tiktok_parser.read_csv(_fixture('tiktok_sample.csv'))
        assert df.shape == (37, 55)

    def test_pipeline_counts_and_order(self, tiktok_parser):
        result = _pipeline(tiktok_parser, _fixture('tiktok_sample.csv'))
        assert result['cancelled_count'] == 6
        assert result['preorder_count'] == 0
        assert result['confirmed_return_count'] == 0
        assert len(result['invoices']) == 27
        assert list(result['invoices'].keys())[:5] == [
            '582404654532953845', '582388342902654141', '582425216767329587',
            '582423177219835344', '582417503805277213',
        ]

    def test_invoice_totals(self, tiktok_parser):
        result = _pipeline(tiktok_parser, _fixture('tiktok_sample.csv'))
        inv = result['invoices']['582404654532953845']
        assert inv.grand_total == 299.0
        assert inv.vat_amount == 19.56
        assert inv.total_before_vat == 279.44
        assert inv.order_sort_key == '2026-02-02 16:17:45'

    def test_sum_of_grand_totals(self, tiktok_parser):
        result = _pipeline(tiktok_parser, _fixture('tiktok_sample.csv'))
        total = sum(inv.grand_total for inv in result['invoices'].values())
        assert round(total, 2) == 13468.58
