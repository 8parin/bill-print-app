"""
Parse context: the small bundle of state a CSV parse run needs.

This module owns ParseContext — a dataclass holding the platform preset
(or None), the resolved column_map, and the vat_rate — plus the logic for
resolving column_map from (custom_column_map, platform, default) and for
validating/describing that mapping. Everything here is pure state and
lookups; it does not read files, filter dataframes, or build Invoice
objects — those jobs live in csv_io.py, order_filters.py and assembly.py,
which take a ParseContext as an argument instead of owning one.
"""
from typing import List, Tuple

from ..platform_presets import PlatformPreset, SHOPEE_PRESET

# Default column map (Shopee) — kept for backward compatibility
DEFAULT_COLUMN_MAP = SHOPEE_PRESET.column_map

# Required fields that must be mapped
REQUIRED_FIELDS = [
    'order_id',
    'product_name',
    'recipient_name',
    'address',
    'phone'
]


class ParseContext:
    """Holds the resolved (platform, column_map, vat_rate) for a parse run."""

    def __init__(self, vat_rate: float, column_map: dict, platform: PlatformPreset = None):
        self.vat_rate = vat_rate
        self.column_map = column_map
        self.platform = platform

    @classmethod
    def build(cls, vat_rate: float = 0.07, custom_column_map: dict = None,
              platform: PlatformPreset = None) -> "ParseContext":
        """Resolve column_map with priority: custom_column_map > platform preset > default (Shopee)."""
        # Priority: custom_column_map > platform preset > default (Shopee)
        if custom_column_map:
            if platform:
                column_map = platform.column_map.copy()
                column_map.update({k: v.strip() for k, v in custom_column_map.items()})
            else:
                column_map = {k: v.strip() for k, v in custom_column_map.items()}
        elif platform:
            column_map = platform.column_map.copy()
        else:
            column_map = DEFAULT_COLUMN_MAP.copy()

        return cls(vat_rate=vat_rate, column_map=column_map, platform=platform)

    def get_field_definitions(self) -> dict:
        """Return field definitions for UI"""
        return {
            'tax_invoice': 'Tax Invoice / Order Number (grouping key)',
            'order_id': 'Order Number *Required',
            'order_date': 'Order Date',
            'product_name': 'Product Name *Required',
            'variant': 'Product Variant',
            'quantity': 'Quantity',
            'sale_price': 'Unit Price',
            'total': 'Line Total',
            'recipient_name': 'Customer Name *Required',
            'phone': 'Phone Number *Required',
            'address': 'Address *Required',
            'tracking_number': 'Tracking Number',
            'shopee_discount': 'Discount',
            'shipping_buyer': 'Shipping Fee',
            'service_fee': 'Service Fee',
            'grand_total': 'Grand Total'
        }

    def update_column_mapping(self, new_mapping: dict):
        """Update column mapping"""
        self.column_map = {k: v.strip() for k, v in new_mapping.items()}

    def validate_mapping(self, mapping: dict) -> Tuple[bool, List[str]]:
        """Validate that all required fields are mapped"""
        errors = []
        for required_field in REQUIRED_FIELDS:
            if required_field not in mapping or not mapping[required_field]:
                errors.append(f"Required field '{required_field}' is not mapped")

        if errors:
            return False, errors
        return True, []
