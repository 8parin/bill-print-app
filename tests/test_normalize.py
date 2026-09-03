"""Unit tests for the pure functions in src/parsing/normalize.py.

Values are pinned from actual behavior of the current implementation (also
exercised indirectly via the golden CSV tests in tests/test_csv_parser.py).
"""
import pandas as pd
import pytest

from src.parsing.context import ParseContext
from src.parsing.normalize import (
    assemble_address,
    clean_numeric,
    format_order_date,
    parse_sort_key,
)
from src.platform_presets import LAZADA_PRESET, TIKTOK_PRESET


class TestCleanNumeric:
    def test_thousands_separator_and_decimal(self):
        assert clean_numeric('1,234.50') == 1234.5

    def test_dash_is_zero(self):
        assert clean_numeric('-') == 0.0

    def test_empty_string_is_zero(self):
        assert clean_numeric('') == 0.0

    def test_none_is_zero(self):
        assert clean_numeric(None) == 0.0

    def test_strips_surrounding_and_internal_whitespace(self):
        assert clean_numeric(' 12 ') == 12.0

    def test_plain_float_passthrough(self):
        assert clean_numeric(3.5) == 3.5

    def test_non_numeric_string_is_zero(self):
        assert clean_numeric('abc') == 0.0


class TestParseSortKey:
    def test_thai_shopee_style_date_with_time(self):
        # DD/MM/YY HH:MM:SS (2-digit year), used by Shopee exports
        assert parse_sort_key('05/01/26 14:30:00') == '2026-01-05 14:30:00'

    def test_iso_date_only(self):
        assert parse_sort_key('2026-01-05') == '2026-01-05 00:00:00'

    def test_lazada_style_date_gets_offset_applied(self):
        context = ParseContext.build(platform=LAZADA_PRESET)
        # Lazada date_offset_days=1
        assert parse_sort_key('13 Feb 2026 09:54', context) == '2026-02-14 09:54:00'

    def test_blank_or_nan_returns_empty_string(self):
        assert parse_sort_key('') == ''
        assert parse_sort_key('nan') == ''

    def test_unparseable_falls_back_to_raw_string(self):
        assert parse_sort_key('not-a-date') == 'not-a-date'


class TestFormatOrderDate:
    def test_thai_format_strips_time(self):
        assert format_order_date('13 Feb 2026 09:54') == '13/02/2026'

    def test_iso_format(self):
        assert format_order_date('2026-01-05') == '05/01/2026'

    def test_tiktok_style_datetime(self):
        assert format_order_date('12/02/2026 22:39:19') == '12/02/2026'

    def test_lazada_offset_applied(self):
        context = ParseContext.build(platform=LAZADA_PRESET)
        assert format_order_date('13 Feb 2026 09:54', context) == '14/02/2026'

    def test_blank_or_nan_passthrough(self):
        assert format_order_date('') == ''
        assert format_order_date('nan') == 'nan'

    def test_unparseable_strips_after_first_space(self):
        assert format_order_date('garbage 123') == 'garbage'
        assert format_order_date('garbage') == 'garbage'


class TestAssembleAddress:
    def test_single_address_column(self):
        context = ParseContext.build(custom_column_map={
            'order_id': 'oid', 'product_name': 'pname', 'recipient_name': 'rname',
            'address': 'addr', 'phone': 'phone',
        })
        row = pd.Series({'addr': '123 Main St\n Bangkok'})
        assert assemble_address(row, context) == '123 Main St Bangkok'

    def test_multi_field_address_joins_nonempty_parts(self):
        context = ParseContext.build(platform=TIKTOK_PRESET)
        row = pd.Series({
            'Detail Address': '99 Sukhumvit Rd',
            'District': 'Watthana',
            'Province': 'Bangkok',
            'Zipcode': '10110',
        })
        assert assemble_address(row, context) == '99 Sukhumvit Rd, Watthana, Bangkok, 10110'

    def test_multi_field_address_skips_blank_and_nan_parts(self):
        context = ParseContext.build(platform=TIKTOK_PRESET)
        row = pd.Series({
            'Detail Address': '99 Sukhumvit Rd',
            'District': '',
            'Province': float('nan'),
            'Zipcode': '10110',
        })
        assert assemble_address(row, context) == '99 Sukhumvit Rd, 10110'

    def test_missing_address_column_returns_empty_string(self):
        context = ParseContext.build(custom_column_map={
            'order_id': 'oid', 'product_name': 'pname', 'recipient_name': 'rname',
            'address': 'addr', 'phone': 'phone',
        })
        row = pd.Series({'other_col': 'value'})
        assert assemble_address(row, context) == ''
