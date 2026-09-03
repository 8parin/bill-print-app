"""
src.parsing — CSV parsing internals for e-commerce platform exports.

Split into five modules by job:
  context.py       — ParseContext (platform, column_map, vat_rate) + mapping validation
  csv_io.py         — reading a CSV file into a DataFrame + column/format validation
  normalize.py      — pure value cleaning (numbers, dates, address text)
  order_filters.py  — status-driven row/invoice filtering (cancelled, preorder, returns, pending)
  assembly.py       — grouping rows by invoice and building Invoice/LineItem/Customer objects

src.csv_parser.CSVParser is a thin backward-compatible facade over this package —
new code should prefer importing directly from these modules.
"""
from .context import ParseContext, REQUIRED_FIELDS, DEFAULT_COLUMN_MAP
from .csv_io import (
    read_csv,
    detect_columns,
    validate_csv,
    validate_csv_format,
    get_column_differences,
)
from .normalize import (
    clean_numeric,
    parse_sort_key,
    format_order_date,
    clean_address,
    assemble_address,
)
from .order_filters import (
    filter_cancelled_invoices,
    filter_preorders,
    filter_confirmed_returns,
    detect_return_items,
    apply_return_decisions,
    split_pending_orders,
    get_pending_summary,
)
from .assembly import group_by_invoice, parse_invoice, parse_csv_to_invoices

__all__ = [
    'ParseContext', 'REQUIRED_FIELDS', 'DEFAULT_COLUMN_MAP',
    'read_csv', 'detect_columns', 'validate_csv', 'validate_csv_format', 'get_column_differences',
    'clean_numeric', 'parse_sort_key', 'format_order_date', 'clean_address', 'assemble_address',
    'filter_cancelled_invoices', 'filter_preorders', 'filter_confirmed_returns',
    'detect_return_items', 'apply_return_decisions', 'split_pending_orders', 'get_pending_summary',
    'group_by_invoice', 'parse_invoice', 'parse_csv_to_invoices',
]
