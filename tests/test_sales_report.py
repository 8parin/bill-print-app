"""Tests for src/sales_report.py: the sales-report module extracted from
app.py's _build_sales_data() and the /sales-report and /sales-report-export
routes (Phase 3).

Pinned values come from running the shopee/lazada/tiktok fixtures through the
real pipeline (src/pipeline.process_csv) exactly as app.py's save_mapping()
route would, then build_sales_data() on the result — so a regression in the
extraction (or in the platform-preset report_columns refactor) shows up here.
"""
import os

import pandas as pd
import pytest

from src.csv_parser import CSVParser
from src.pipeline import process_csv
from src.platform_presets import SHOPEE_PRESET, LAZADA_PRESET, TIKTOK_PRESET
from src.sales_report import build_sales_data, build_sales_report_pdf, build_sales_export_df, SALES_EXPORT_COLUMN_MAP

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


def _fixture(name):
    return os.path.join(FIXTURES_DIR, name)


def _invoice_lookup(invoices):
    return {
        inv.order_id: {
            'shipping': inv.shipping, 'service_fee': inv.service_fee,
            'grand_total': inv.grand_total, 'discount': inv.discount,
            'subtotal': inv.subtotal, 'vat_amount': inv.vat_amount,
            'total_before_vat': inv.total_before_vat,
            'order_sort_key': inv.order_sort_key,
            'order_index': inv.order_index,
        }
        for inv in invoices
    }


def _stamp_bill_numbers(result, bill_prefix, bill_start):
    """Mirror app.py's _assign_bill_numbers() for these standalone tests."""
    for inv in result.invoices:
        inv.bill_number = f"{bill_prefix}{bill_start + inv.order_index}"
    df = result.trimmed_df
    if df is not None and '__bill_order__' in df.columns:
        df['__bill_number__'] = df['__bill_order__'].apply(
            lambda idx: f"{bill_prefix}{bill_start + int(idx)}" if pd.notna(idx) else ''
        )


@pytest.fixture
def shopee_sales_data():
    parser = CSVParser(platform=SHOPEE_PRESET)
    result = process_csv(parser, _fixture('shopee_sample.csv'))
    _stamp_bill_numbers(result, '', 2600001)
    df = result.trimmed_df.copy()
    sd = build_sales_data(
        df, SHOPEE_PRESET, parser.column_map, _invoice_lookup(result.invoices), '', 2600001
    )
    return sd, result


class TestBuildSalesDataShopee:
    def test_row_and_order_counts(self, shopee_sales_data):
        sd, result = shopee_sales_data
        # 3 invoices (order_id groups) => 11 line-item rows across them
        assert len(sd['report_rows']) == 11
        assert len(sd['seen_orders']) == 3
        assert sd['total_qty'] == 11.0

    def test_first_order_actual_receive_and_total_fee(self, shopee_sales_data):
        sd, result = shopee_sales_data
        first_row = sd['report_rows'][0]
        assert first_row['order_id'] == '260203QN0QGY27'
        assert first_row['bill_number'] == '2600001'
        assert first_row['grand_total'] == 264.0
        assert first_row['actual_receive'] == 124.0
        assert first_row['total_fee'] == 35.0

    def test_sum_of_qty_matches_total_qty(self, shopee_sales_data):
        sd, _ = shopee_sales_data
        assert sum(r['qty'] for r in sd['report_rows']) == sd['total_qty']

    def test_actual_receive_and_fee_sums(self, shopee_sales_data):
        sd, _ = shopee_sales_data
        assert round(sum(sd['order_actual_receive'].values()), 2) == 1750.0
        assert round(sum(sd['order_total_fee'].values()), 2) == 192.0


class TestBuildSalesReportPdf:
    def test_returns_nonempty_pdf_bytes(self, shopee_sales_data):
        sd, result = shopee_sales_data
        pdf_bytes = build_sales_report_pdf(sd, result.invoices)
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0
        assert pdf_bytes.startswith(b'%PDF')


class TestBuildSalesExportDf:
    def test_headers_are_the_26_thai_columns_in_order(self, shopee_sales_data):
        sd, _ = shopee_sales_data
        export_df = build_sales_export_df(sd['report_rows'])
        assert list(export_df.columns) == list(SALES_EXPORT_COLUMN_MAP.values())
        assert len(export_df.columns) == 26
        assert len(export_df) == len(sd['report_rows'])


class TestBuildSalesDataOtherPlatforms:
    """Lazada/TikTok have no report_columns preset override, so they ride the
    same Shopee-default fuzzy find_col() lookup that existed before this
    module was extracted — the columns simply aren't found, resolving to
    0/None. The point of these tests is just that build_sales_data() doesn't
    crash for non-Shopee input."""

    def test_lazada_does_not_crash(self):
        parser = CSVParser(platform=LAZADA_PRESET)
        result = process_csv(parser, _fixture('lazada_sample.csv'), decisions=[])
        _stamp_bill_numbers(result, '', 2600001)
        df = result.trimmed_df.copy()
        sd = build_sales_data(
            df, LAZADA_PRESET, parser.column_map, _invoice_lookup(result.invoices), '', 2600001
        )
        assert len(sd['report_rows']) == len(df)
        # Shopee-only columns never resolve for Lazada -> stay at their zero default
        assert all(r['commission'] in (0.0, None) for r in sd['report_rows'])

    def test_tiktok_does_not_crash(self):
        parser = CSVParser(platform=TIKTOK_PRESET)
        result = process_csv(parser, _fixture('tiktok_sample.csv'), decisions=[])
        _stamp_bill_numbers(result, '', 2600001)
        df = result.trimmed_df.copy()
        sd = build_sales_data(
            df, TIKTOK_PRESET, parser.column_map, _invoice_lookup(result.invoices), '', 2600001
        )
        assert len(sd['report_rows']) == len(df)
        assert all(r['commission'] in (0.0, None) for r in sd['report_rows'])


class TestBuildSalesDataNoPreset:
    """The custom-mapping path (preset=None) must still fall back to the
    hardcoded Shopee default column names, matching pre-refactor behavior."""

    def test_none_preset_falls_back_to_shopee_defaults(self, shopee_sales_data):
        sd_with_preset, result = shopee_sales_data
        parser = CSVParser(platform=SHOPEE_PRESET)
        df = result.trimmed_df.copy()
        sd_no_preset = build_sales_data(
            df, None, parser.column_map, _invoice_lookup(result.invoices), '', 2600001
        )
        # Same underlying Shopee CSV, same column names looked up either way
        # (via preset.report_columns or the _DEFAULT_REPORT_COLUMNS fallback)
        # -> identical numeric results.
        assert sd_no_preset['report_rows'][0]['actual_receive'] == sd_with_preset['report_rows'][0]['actual_receive']
        assert sd_no_preset['total_qty'] == sd_with_preset['total_qty']
