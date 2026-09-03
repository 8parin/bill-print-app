"""
CSV Parser for e-commerce platform export files (Shopee, Lazada, TikTok Shop)

CSVParser is a thin backward-compatible facade over the src/parsing/ package
(context, csv_io, normalize, order_filters, assembly). It exists so existing
callers (src/pipeline.py, src/web/, tests/) keep working unchanged; new code
should prefer importing directly from src.parsing.
"""
from typing import Dict, List, Tuple

import pandas as pd

from .bill_data import Invoice
from .platform_presets import PlatformPreset, SHOPEE_PRESET
from .parsing.context import ParseContext, REQUIRED_FIELDS
from .parsing import csv_io, normalize, order_filters, assembly


class CSVParser:
    """Parse and validate e-commerce CSV files"""

    # Default column map (Shopee) — kept for backward compatibility
    COLUMN_MAP = SHOPEE_PRESET.column_map

    # Default statuses (Shopee) — kept for backward compatibility
    CANCELLED_STATUSES = SHOPEE_PRESET.cancelled_statuses
    CONFIRMED_RETURN_STATUSES = SHOPEE_PRESET.confirmed_return_statuses

    # Required fields that must be mapped
    REQUIRED_FIELDS = REQUIRED_FIELDS

    def __init__(self, vat_rate: float = 0.07, custom_column_map: dict = None,
                 platform: PlatformPreset = None):
        self._context = ParseContext.build(
            vat_rate=vat_rate, custom_column_map=custom_column_map, platform=platform
        )
        # first_column_warning is set as a side effect of read_csv(); the upload
        # route reads it off the parser instance afterwards.
        self.first_column_warning = None

    # -- state exposed for backward compatibility (pipeline.py, web/, tests) --

    @property
    def vat_rate(self):
        return self._context.vat_rate

    @vat_rate.setter
    def vat_rate(self, value):
        self._context.vat_rate = value

    @property
    def column_map(self):
        return self._context.column_map

    @column_map.setter
    def column_map(self, value):
        self._context.column_map = value

    @property
    def platform(self):
        return self._context.platform

    @platform.setter
    def platform(self, value):
        self._context.platform = value

    # -- context.py delegation --

    def get_field_definitions(self) -> dict:
        """Return field definitions for UI"""
        return self._context.get_field_definitions()

    def update_column_mapping(self, new_mapping: dict):
        """Update column mapping"""
        self._context.update_column_mapping(new_mapping)

    def validate_mapping(self, mapping: dict) -> Tuple[bool, List[str]]:
        """Validate that all required fields are mapped"""
        return self._context.validate_mapping(mapping)

    # -- csv_io.py delegation --

    def read_csv(self, file_path: str) -> pd.DataFrame:
        """Read CSV file with proper encoding. Sets self.first_column_warning
        as a side effect (consumed by the upload route)."""
        df, warning = csv_io.read_csv(self._context, file_path)
        self.first_column_warning = warning
        return df

    def detect_columns(self, file_path: str) -> List[str]:
        """Detect all columns in the CSV file"""
        return csv_io.detect_columns(self._context, file_path)

    def validate_csv(self, df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """Validate CSV has required columns"""
        return csv_io.validate_csv(self._context, df)

    def validate_csv_format(self, df: pd.DataFrame) -> Tuple[bool, dict]:
        """Enhanced validation with detailed format change detection"""
        return csv_io.validate_csv_format(self._context, df)

    def get_column_differences(self, detected_columns: List[str]) -> dict:
        """Compare detected columns with expected mapping"""
        return csv_io.get_column_differences(self._context, detected_columns)

    # -- normalize.py delegation --

    def _parse_sort_key(self, raw_date: str) -> str:
        return normalize.parse_sort_key(raw_date, self._context)

    def format_order_date(self, raw_date: str) -> str:
        return normalize.format_order_date(raw_date, self._context)

    def clean_numeric(self, value) -> float:
        return normalize.clean_numeric(value)

    @staticmethod
    def _clean_address(text: str) -> str:
        return normalize.clean_address(text)

    def assemble_address(self, row) -> str:
        return normalize.assemble_address(row, self._context)

    # -- order_filters.py delegation --

    def _get_cancelled_statuses(self) -> list:
        return order_filters._get_cancelled_statuses(self._context)

    def _get_confirmed_return_statuses(self) -> list:
        return order_filters._get_confirmed_return_statuses(self._context)

    def _needs_forward_fill(self) -> bool:
        return order_filters._needs_forward_fill(self._context)

    def _get_invoice_level_fields(self) -> list:
        return order_filters._get_invoice_level_fields(self._context)

    def _forward_fill_invoice_fields(self, df: pd.DataFrame) -> pd.DataFrame:
        return order_filters._forward_fill_invoice_fields(self._context, df)

    def filter_cancelled_invoices(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
        return order_filters.filter_cancelled_invoices(self._context, df)

    def filter_preorders(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
        return order_filters.filter_preorders(self._context, df)

    def filter_confirmed_returns(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
        return order_filters.filter_confirmed_returns(self._context, df)

    def detect_return_items(self, df: pd.DataFrame) -> List[dict]:
        return order_filters.detect_return_items(self._context, df)

    def apply_return_decisions(self, df: pd.DataFrame, decisions: List[dict]) -> pd.DataFrame:
        return order_filters.apply_return_decisions(self._context, df, decisions)

    def split_pending_orders(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        return order_filters.split_pending_orders(self._context, df)

    def get_pending_summary(self, pending_df: pd.DataFrame) -> list:
        return order_filters.get_pending_summary(self._context, pending_df)

    # -- assembly.py delegation --

    def group_by_invoice(self, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        return assembly.group_by_invoice(self._context, df)

    def parse_invoice(self, invoice_df: pd.DataFrame, invoice_number: str) -> Invoice:
        return assembly.parse_invoice(self._context, invoice_df, invoice_number)

    def parse_csv_to_invoices(self, file_path: str) -> List[Invoice]:
        """Main function: Read CSV and return list of Invoice objects"""
        invoices, cancelled_count, preorder_count = assembly.parse_csv_to_invoices(self._context, file_path)
        self.last_cancelled_count = cancelled_count
        self.last_preorder_count = preorder_count
        return invoices
