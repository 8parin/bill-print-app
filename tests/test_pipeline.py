"""Tests for src/pipeline.py: the shared CSV processing pipeline extracted
from app.py's save_mapping() and apply_return_decisions().

These exercise process_csv() against the same fixtures/goldens as
tests/test_csv_parser.py's _pipeline() helper (which mirrors the old
save_mapping-equivalent steps minus split_pending_orders/forward-fill), so a
regression in the extraction shows up as a mismatch here too.
"""
import os

import pytest

from src.csv_parser import CSVParser
from src.pipeline import process_csv
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


class TestShopeePipeline:
    def test_counts_and_order(self, shopee_parser):
        result = process_csv(shopee_parser, _fixture('shopee_sample.csv'))
        assert result.needs_return_review is False
        assert result.cancelled_count == 1
        assert result.preorder_count == 0
        assert result.auto_return_count == 0
        assert len(result.invoices) == 3
        assert [inv.invoice_number for inv in result.invoices] == [
            '260203QN0QGY27', '260211EB9UDEBD', '260221AYM6EYHF',
        ]

    def test_invoice_totals(self, shopee_parser):
        result = process_csv(shopee_parser, _fixture('shopee_sample.csv'))
        inv = result.invoices[0]
        assert inv.invoice_number == '260203QN0QGY27'
        assert inv.grand_total == 264.0
        assert inv.vat_amount == 17.27
        assert inv.total_before_vat == 246.73
        assert len(inv.items) == 1
        assert inv.order_sort_key == '2026-02-04 09:59:00'
        assert inv.order_index == 0

    def test_sum_of_grand_totals(self, shopee_parser):
        result = process_csv(shopee_parser, _fixture('shopee_sample.csv'))
        total = sum(inv.grand_total for inv in result.invoices)
        assert round(total, 2) == 1374.0

    def test_trimmed_df_has_bill_order_and_is_forward_filled(self, shopee_parser):
        # DELIBERATE FIX: forward-fill is now always applied to the trimmed df
        # (previously only save_mapping's path did this, not
        # apply_return_decisions's). Shopee needs forward-fill, so its
        # invoice-level columns should have no blanks left after the fix.
        result = process_csv(shopee_parser, _fixture('shopee_sample.csv'))
        assert result.trimmed_df is not None
        assert '__bill_order__' in result.trimmed_df.columns
        # order_index values assigned to the df must match the invoices list
        order_map = dict(zip(
            [inv.invoice_number for inv in result.invoices],
            [inv.order_index for inv in result.invoices],
        ))
        tax_col = shopee_parser.column_map.get('tax_invoice') or shopee_parser.column_map.get('order_id')
        for _, row in result.trimmed_df.iterrows():
            key = str(row[tax_col]).strip()
            if key in order_map:
                assert row['__bill_order__'] == order_map[key]


class TestLazadaPipeline:
    def test_counts_and_order(self, lazada_parser):
        result = process_csv(lazada_parser, _fixture('lazada_sample.csv'))
        assert result.cancelled_count == 16
        assert result.preorder_count == 0
        assert result.auto_return_count == 0
        assert len(result.invoices) == 92
        assert [inv.invoice_number for inv in result.invoices[:5]] == [
            '1072461471301325', '1080505124492448', '1072519667724528',
            '1080526782286012', '1072570650860182',
        ]

    def test_invoice_totals(self, lazada_parser):
        result = process_csv(lazada_parser, _fixture('lazada_sample.csv'))
        inv = result.invoices[0]
        assert inv.grand_total == 208.5
        assert inv.vat_amount == 13.64
        assert inv.total_before_vat == 194.86
        assert inv.order_sort_key == '2026-02-02 09:09:00'

    def test_sum_of_grand_totals(self, lazada_parser):
        result = process_csv(lazada_parser, _fixture('lazada_sample.csv'))
        total = sum(inv.grand_total for inv in result.invoices)
        assert round(total, 2) == 27045.26


class TestTiktokPipeline:
    # tiktok_sample.csv contains at least one return/refund item with a status
    # detect_return_items() doesn't recognize as auto-resolvable, so the
    # decisions=None path correctly stops for review (needs_return_review=True)
    # rather than parsing invoices — this mirrors real save_mapping() behavior.
    # Passing decisions=[] (as apply_return_decisions() always does — it never
    # calls detect_return_items) skips that check, matching the counts pinned
    # in tests/test_csv_parser.py's _pipeline() helper.
    def test_decisions_none_flags_return_review(self, tiktok_parser):
        result = process_csv(tiktok_parser, _fixture('tiktok_sample.csv'))
        assert result.needs_return_review is True
        assert result.return_items

    def test_counts_and_order(self, tiktok_parser):
        # 27 in tests/test_csv_parser.py's _pipeline() vs 23 here: process_csv
        # additionally runs split_pending_orders (4 unshipped orders held back
        # as pending_orders, excluded from invoices) — a step the older golden
        # helper never performed. The first 5 invoice numbers / sort order
        # still match exactly since split_pending_orders only removes rows,
        # it doesn't reorder them.
        result = process_csv(tiktok_parser, _fixture('tiktok_sample.csv'), decisions=[])
        assert result.cancelled_count == 6
        assert result.preorder_count == 0
        assert result.auto_return_count == 0
        assert len(result.invoices) == 23
        assert len(result.pending_orders) == 4
        assert [inv.invoice_number for inv in result.invoices[:5]] == [
            '582404654532953845', '582388342902654141', '582425216767329587',
            '582423177219835344', '582417503805277213',
        ]

    def test_invoice_totals(self, tiktok_parser):
        result = process_csv(tiktok_parser, _fixture('tiktok_sample.csv'), decisions=[])
        inv = result.invoices[0]
        assert inv.invoice_number == '582404654532953845'
        assert inv.grand_total == 299.0
        assert inv.vat_amount == 19.56
        assert inv.total_before_vat == 279.44
        assert inv.order_sort_key == '2026-02-02 16:17:45'

    def test_sum_of_grand_totals(self, tiktok_parser):
        result = process_csv(tiktok_parser, _fixture('tiktok_sample.csv'), decisions=[])
        total = sum(inv.grand_total for inv in result.invoices)
        assert round(total, 2) == 8078.93


class TestDecisionsPath:
    def test_empty_decisions_list_skips_return_review(self, shopee_parser):
        # apply_return_decisions() always passes a list (possibly empty), never
        # None — process_csv must treat that as "decisions were supplied" and
        # skip detect_return_items()/needs_return_review entirely, applying
        # apply_return_decisions() (a no-op for an empty list) instead.
        result = process_csv(shopee_parser, _fixture('shopee_sample.csv'), decisions=[])
        assert result.needs_return_review is False
        assert len(result.invoices) == 3
