"""
CSV Parser for e-commerce platform export files (Shopee, Lazada, TikTok Shop)
"""
import re
from datetime import datetime, timedelta
import pandas as pd
from typing import Dict, List, Tuple, Optional
from .bill_data import Invoice, Customer, LineItem
from .platform_presets import PlatformPreset, SHOPEE_PRESET


class CSVParser:
    """Parse and validate e-commerce CSV files"""

    # Default column map (Shopee) — kept for backward compatibility
    COLUMN_MAP = SHOPEE_PRESET.column_map

    # Default statuses (Shopee) — kept for backward compatibility
    CANCELLED_STATUSES = SHOPEE_PRESET.cancelled_statuses
    CONFIRMED_RETURN_STATUSES = SHOPEE_PRESET.confirmed_return_statuses

    # Required fields that must be mapped
    REQUIRED_FIELDS = [
        'order_id',
        'product_name',
        'recipient_name',
        'address',
        'phone'
    ]

    def __init__(self, vat_rate: float = 0.07, custom_column_map: dict = None,
                 platform: PlatformPreset = None):
        self.vat_rate = vat_rate
        self.platform = platform

        # Priority: custom_column_map > platform preset > default (Shopee)
        if custom_column_map:
            if platform:
                self.column_map = platform.column_map.copy()
                self.column_map.update({k: v.strip() for k, v in custom_column_map.items()})
            else:
                self.column_map = {k: v.strip() for k, v in custom_column_map.items()}
        elif platform:
            self.column_map = platform.column_map.copy()
        else:
            self.column_map = self.COLUMN_MAP.copy()

    def detect_columns(self, file_path: str) -> List[str]:
        """Detect all columns in the CSV file"""
        df = self.read_csv(file_path)
        return list(df.columns)

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
        for required_field in self.REQUIRED_FIELDS:
            if required_field not in mapping or not mapping[required_field]:
                errors.append(f"Required field '{required_field}' is not mapped")

        if errors:
            return False, errors
        return True, []

    def read_csv(self, file_path: str) -> pd.DataFrame:
        """Read CSV file with proper encoding. dtype=str prevents large integers
        (e.g. order IDs) from being converted to float and displaying as 5.82E+17 in Excel."""
        try:
            df = pd.read_csv(file_path, encoding='utf-8', dtype=str)
        except UnicodeDecodeError:
            df = pd.read_csv(file_path, encoding='tis-620', dtype=str)

        # Strip whitespace and BOM from column names
        df.columns = [col.strip().lstrip('\ufeff') for col in df.columns]

        # Platform-specific: skip metadata rows (e.g. TikTok row 2)
        if self.platform and self.platform.skip_rows:
            rows_to_skip = [i for i in self.platform.skip_rows if i < len(df)]
            if rows_to_skip:
                df = df.drop(index=rows_to_skip).reset_index(drop=True)

        # First-column validation (only for Shopee)
        self.first_column_warning = None
        if self.platform and self.platform.name == 'shopee':
            first_col = df.columns[0] if len(df.columns) > 0 else ''
            expected_first = self.column_map.get('order_id', '')
            if first_col != expected_first:
                self.first_column_warning = (
                    f"First column is '{first_col}' instead of '{expected_first}'. "
                    f"The CSV file may be corrupted — please re-export from Shopee."
                )
        elif not self.platform:
            # Legacy behavior when no platform specified
            first_col = df.columns[0] if len(df.columns) > 0 else ''
            if first_col != 'หมายเลขคำสั่งซื้อ':
                self.first_column_warning = (
                    f"First column is '{first_col}' instead of 'หมายเลขคำสั่งซื้อ'. "
                    f"The CSV file may be corrupted — please re-export."
                )

        return df

    def validate_csv(self, df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """Validate CSV has required columns"""
        errors = []
        required_cols = [
            self.column_map['order_id'],
            self.column_map['product_name'],
            self.column_map['recipient_name']
        ]

        for col in required_cols:
            if col not in df.columns:
                errors.append(f"Missing required column: {col}")

        if errors:
            return False, errors
        return True, []

    def validate_csv_format(self, df: pd.DataFrame) -> Tuple[bool, dict]:
        """Enhanced validation with detailed format change detection"""
        result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'missing_columns': [],
            'extra_columns': [],
            'format_changed': False
        }

        detected_cols = set(df.columns)
        expected_cols = set(self.column_map.values())

        # Check for missing required columns
        required_fields = ['order_id', 'product_name', 'recipient_name', 'address', 'phone']
        for field in required_fields:
            col_name = self.column_map.get(field, '')
            if col_name and col_name not in detected_cols:
                # For multi-field addresses, check the primary field
                result['missing_columns'].append({
                    'field': field,
                    'expected_name': col_name
                })
                result['errors'].append(
                    f"❌ Required column missing: '{col_name}' (used for {field})"
                )

        # Check for extra columns
        extra_cols = detected_cols - expected_cols
        if extra_cols:
            result['extra_columns'] = list(extra_cols)
            result['warnings'].append(
                f"⚠️ Found {len(extra_cols)} unknown columns: {', '.join(list(extra_cols)[:3])}{'...' if len(extra_cols) > 3 else ''}"
            )

        # Check if format has significantly changed
        missing_count = len(result['missing_columns'])
        if missing_count > 0:
            result['format_changed'] = True
            result['valid'] = False

            platform_name = self.platform.display_name if self.platform else 'the platform'
            result['errors'].insert(0,
                f"🚨 CSV FORMAT CHANGED: {missing_count} required column(s) not found!"
            )
            result['errors'].append(
                f"\n💡 This usually happens when {platform_name} updates their export format."
            )
            result['errors'].append(
                "Please go to Step 2 to remap the columns to match the new CSV format."
            )

        return result['valid'], result

    def get_column_differences(self, detected_columns: List[str]) -> dict:
        """Compare detected columns with expected mapping"""
        expected = set(self.column_map.values())
        detected = set(detected_columns)

        return {
            'expected_columns': list(expected),
            'detected_columns': detected_columns,
            'missing': list(expected - detected),
            'extra': list(detected - expected),
            'matched': list(expected & detected)
        }

    def _parse_sort_key(self, raw_date: str) -> str:
        """Return sortable ISO string (YYYY-MM-DD HH:MM:SS) from raw date column value.

        Used for ordering invoices by datetime. Time is preserved here so
        same-day orders sort correctly. Time is trimmed only at display time
        via format_order_date.
        """
        if not raw_date or raw_date == 'nan':
            return ''
        date_str = str(raw_date).strip()
        date_formats = [
            '%d %b %Y %H:%M',
            '%d %b %Y %H:%M:%S',
            '%d/%m/%Y %H:%M:%S',
            '%d/%m/%Y %H:%M',
            '%d/%m/%y %H:%M:%S',   # Shopee: DD/MM/YY HH:MM:SS (2-digit year)
            '%d/%m/%y %H:%M',      # Shopee: DD/MM/YY HH:MM (2-digit year)
            '%Y-%m-%d %H:%M',
            '%Y-%m-%d %H:%M:%S',
            '%Y/%m/%d %H:%M',
            '%Y/%m/%d %H:%M:%S',
            '%d %b %Y',
            '%d/%m/%Y',
            '%d/%m/%y',            # Shopee: DD/MM/YY (2-digit year, date only)
            '%Y-%m-%d',
            '%Y/%m/%d',
        ]
        for fmt in date_formats:
            try:
                parsed = datetime.strptime(date_str, fmt)
                if self.platform and getattr(self.platform, 'date_offset_days', 0):
                    parsed += timedelta(days=self.platform.date_offset_days)
                return parsed.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                continue
        return date_str  # fallback: use raw string (works for ISO-like formats)

    def format_order_date(self, raw_date: str) -> str:
        """Format order date: strip time portion and apply platform date offset.

        - All platforms: remove time, keep date only
        - Lazada: +1 day offset (createTime is 1 day behind)
        """
        if not raw_date or raw_date == 'nan':
            return raw_date

        date_str = str(raw_date).strip()

        # Try common date(time) formats
        date_formats = [
            '%d %b %Y %H:%M',     # 13 Feb 2026 09:54 (Lazada)
            '%d %b %Y %H:%M:%S',  # 13 Feb 2026 09:54:00
            '%d/%m/%Y %H:%M:%S',  # 12/02/2026 22:39:19 (TikTok)
            '%d/%m/%Y %H:%M',     # 05/01/2026 14:30
            '%Y-%m-%d %H:%M',     # 2026-01-05 14:30
            '%Y-%m-%d %H:%M:%S',  # 2026-01-05 14:30:00
            '%Y/%m/%d %H:%M',     # 2026/01/05 14:30
            '%Y/%m/%d %H:%M:%S',  # 2026/01/05 14:30:00
            '%d %b %Y',           # 13 Feb 2026
            '%d/%m/%Y',           # 05/01/2026
            '%Y-%m-%d',           # 2026-01-05
            '%Y/%m/%d',           # 2026/01/05
        ]

        parsed_date = None
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue

        if parsed_date is None:
            # Fallback: just strip everything after first space (remove time)
            return date_str.split(' ')[0] if ' ' in date_str else date_str

        # Apply date offset if platform specifies it
        offset = 0
        if self.platform and hasattr(self.platform, 'date_offset_days'):
            offset = self.platform.date_offset_days
        if offset:
            parsed_date += timedelta(days=offset)

        return parsed_date.strftime('%d/%m/%Y')

    def clean_numeric(self, value) -> float:
        """Clean and convert numeric values"""
        if pd.isna(value) or value == '' or value == '-':
            return 0.0

        if isinstance(value, str):
            value = value.strip().replace(',', '').replace(' ', '')
            if value == '' or value == '-':
                return 0.0

        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    def _get_cancelled_statuses(self) -> list:
        """Get cancelled statuses from platform or defaults"""
        if self.platform:
            return self.platform.cancelled_statuses
        return self.CANCELLED_STATUSES

    def _get_confirmed_return_statuses(self) -> list:
        """Get confirmed return statuses from platform or defaults"""
        if self.platform:
            return self.platform.confirmed_return_statuses
        return self.CONFIRMED_RETURN_STATUSES

    def _needs_forward_fill(self) -> bool:
        """Check if platform needs forward-fill for invoice-level fields"""
        if self.platform:
            return self.platform.needs_forward_fill
        return True  # default (Shopee behavior)

    def _get_invoice_level_fields(self) -> list:
        """Get list of invoice-level field keys for forward-fill"""
        if self.platform and self.platform.invoice_level_fields:
            return self.platform.invoice_level_fields
        # Default (Shopee)
        return [
            'order_id', 'tax_invoice', 'order_date', 'recipient_name',
            'phone', 'address', 'tracking_number', 'shopee_discount',
            'shipping_buyer', 'service_fee', 'grand_total', 'estimated_shipping',
        ]

    def _forward_fill_invoice_fields(self, df: pd.DataFrame) -> pd.DataFrame:
        """Forward-fill invoice-level fields if platform requires it"""
        if not self._needs_forward_fill():
            return df

        for field_key in self._get_invoice_level_fields():
            col = self.column_map.get(field_key)
            if col and col in df.columns:
                df[col] = df[col].replace('', pd.NA)
                df[col] = df[col].ffill()
        return df

    def assemble_address(self, row) -> str:
        """Assemble address from one or more CSV columns.

        For Shopee: single 'address' column.
        For Lazada: shippingAddress + shippingAddress2-5 + city + postcode.
        For TikTok: Detail Address + District + Province + Zipcode.
        """
        if self.platform and len(self.platform.address_fields) > 1:
            parts = []
            for col_name in self.platform.address_fields:
                if col_name in row.index:
                    val = str(row[col_name]).strip() if pd.notna(row[col_name]) else ''
                    if val and val != 'nan':
                        parts.append(val)
            return ', '.join(parts) if parts else ''
        else:
            addr_col = self.column_map.get('address', '')
            if addr_col and addr_col in row.index:
                return str(row[addr_col])
            return ''

    def filter_cancelled_invoices(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
        """Filter out entire invoices where any row has a cancelled status.

        Returns the filtered DataFrame and count of removed invoices.
        """
        status_col = self.column_map.get('order_status')
        order_col = self.column_map['order_id']

        if not status_col or status_col not in df.columns:
            return df, 0

        # For Shopee-style CSVs (needs_forward_fill=True), the 2nd+ item rows of
        # each order have a blank order_id. Forward-fill order_id first so those
        # rows are correctly identified as belonging to the cancelled order.
        df = df.copy()
        if self._needs_forward_fill() and order_col in df.columns:
            df[order_col] = df[order_col].replace('', pd.NA).ffill()

        cancelled_statuses = self._get_cancelled_statuses()
        cancelled_mask = df[status_col].astype(str).str.strip().isin(cancelled_statuses)
        cancelled_order_ids = df.loc[cancelled_mask, order_col].unique()

        if len(cancelled_order_ids) == 0:
            return df, 0

        df_filtered = df[~df[order_col].isin(cancelled_order_ids)]
        return df_filtered, len(cancelled_order_ids)

    def filter_confirmed_returns(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
        """Auto-remove item rows with confirmed return status.

        For Shopee-style CSVs (needs_forward_fill=True), invoice-level fields
        (customer name, address, order_id, etc.) are forward-filled FIRST so that
        order-level info is preserved even when the returned item is in the first
        row of the order (row1 also carries the customer/address data).

        Returns (filtered_df, removed_item_count).
        """
        if self.platform and self.platform.return_status_field is None:
            return df, 0

        return_col_key = 'return_status'
        if self.platform and self.platform.return_status_field:
            return_col_key = self.platform.return_status_field

        return_col = self.column_map.get(return_col_key)
        if not return_col or return_col not in df.columns:
            return df, 0

        confirmed_statuses = self._get_confirmed_return_statuses()
        if not confirmed_statuses:
            return df, 0

        # Forward-fill invoice-level fields first so that if the returned item is
        # in row1, its order-level info (customer, address, order_id, etc.) is
        # propagated to the remaining item rows before that row is deleted.
        df = self._forward_fill_invoice_fields(df.copy())

        return_mask = df[return_col].astype(str).str.strip().isin(confirmed_statuses)
        rows_to_drop = df.index[return_mask].tolist()

        if not rows_to_drop:
            return df, 0

        df_filtered = df.drop(index=rows_to_drop)
        return df_filtered, len(rows_to_drop)

    def detect_return_items(self, df: pd.DataFrame) -> List[dict]:
        """Detect rows with return/refund statuses.

        Returns a list of flagged items with their details and category:
        - 'confirmed': status is in confirmed return statuses
        - 'unknown': non-blank status not in confirmed list
        """
        # If platform explicitly has no return column, skip
        if self.platform and self.platform.return_status_field is None:
            return []

        return_col_key = 'return_status'
        if self.platform and self.platform.return_status_field:
            return_col_key = self.platform.return_status_field

        return_col = self.column_map.get(return_col_key)
        if not return_col or return_col not in df.columns:
            return []

        order_col = self.column_map['order_id']
        product_col = self.column_map['product_name']
        variant_col = self.column_map.get('variant')

        confirmed_statuses = self._get_confirmed_return_statuses()

        flagged = []
        for idx, row in df.iterrows():
            status = str(row[return_col]).strip() if pd.notna(row[return_col]) else ''
            if status == '' or status == 'nan':
                continue

            order_id = str(row[order_col])
            product = str(row[product_col])
            variant = ''
            if variant_col and variant_col in df.columns:
                variant = str(row[variant_col]) if pd.notna(row[variant_col]) else ''

            category = 'confirmed' if status in confirmed_statuses else 'unknown'

            flagged.append({
                'row_index': int(idx),
                'order_id': order_id,
                'product': product,
                'variant': variant,
                'return_status': status,
                'category': category
            })

        return flagged

    def apply_return_decisions(self, df: pd.DataFrame, decisions: List[dict]) -> pd.DataFrame:
        """Apply user decisions about return items.

        Each decision dict has:
        - row_index: the DataFrame row index
        - action: 'keep' | 'remove_product' | 'remove_bill'
        """
        order_col = self.column_map['order_id']

        # Forward-fill if needed so we can correctly identify invoice grouping
        df = self._forward_fill_invoice_fields(df)

        rows_to_drop = set()
        orders_to_drop = set()

        for decision in decisions:
            action = decision.get('action', 'keep')
            row_idx = decision.get('row_index')

            if action == 'remove_product' and row_idx is not None:
                rows_to_drop.add(row_idx)
            elif action == 'remove_bill' and row_idx is not None:
                if row_idx in df.index:
                    order_id = df.loc[row_idx, order_col]
                    orders_to_drop.add(order_id)

        if orders_to_drop:
            df = df[~df[order_col].isin(orders_to_drop)]

        if rows_to_drop:
            df = df.drop(index=[i for i in rows_to_drop if i in df.index])

        return df

    def split_pending_orders(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Split df into (shipped_df, pending_df) based on primary date column being NaN.

        Only applies to platforms with date_fallback_columns (e.g. TikTok: Shipped Time can be NaN).
        Pending orders are excluded from bills/sales report and shown on a separate summary page.
        Returns (shipped_df, pending_df); pending_df is empty if platform has no fallback columns.
        """
        if not (self.platform and self.platform.date_fallback_columns):
            return df, pd.DataFrame(columns=df.columns)

        order_date_col = self.column_map.get('order_date')
        if not order_date_col or order_date_col not in df.columns:
            return df, pd.DataFrame(columns=df.columns)

        tax_invoice_col = self.column_map.get('tax_invoice', self.column_map.get('order_id'))
        date_is_nan = df[order_date_col].isna() | (df[order_date_col].astype(str).str.strip().isin(['nan', 'NaT', '']))
        pending_ids = df.loc[date_is_nan, tax_invoice_col].dropna().unique()

        if len(pending_ids) == 0:
            return df, pd.DataFrame(columns=df.columns)

        # For platforms with shipped_statuses: orders with a "shipped" status should always
        # get a bill even if their primary date column (e.g. Shipped Time) is NaN.
        # This covers TikTok orders with substatus "อยู่ระหว่างขนส่ง" that lack Shipped Time.
        shipped_statuses = getattr(self.platform, 'shipped_statuses', []) if self.platform else []
        status_col = self.column_map.get('order_status')
        if shipped_statuses and status_col and status_col in df.columns:
            shipped_mask = df[status_col].astype(str).str.strip().isin(shipped_statuses)
            shipped_order_ids = set(df.loc[shipped_mask, tax_invoice_col].dropna().unique())
            pending_ids = [oid for oid in pending_ids if oid not in shipped_order_ids]

        if len(pending_ids) == 0:
            return df, pd.DataFrame(columns=df.columns)

        shipped_df = df[~df[tax_invoice_col].isin(pending_ids)].copy()
        pending_df = df[df[tax_invoice_col].isin(pending_ids)].copy()
        return shipped_df, pending_df

    def get_pending_summary(self, pending_df: pd.DataFrame) -> list:
        """Extract summary rows from pending (unshipped) orders for the summary page."""
        if pending_df.empty:
            return []

        tax_invoice_col = self.column_map.get('tax_invoice', self.column_map.get('order_id'))
        recipient_col = self.column_map.get('recipient_name', '')
        phone_col = self.column_map.get('phone', '')
        product_col = self.column_map.get('product_name', '')
        qty_col = self.column_map.get('quantity', '')
        variant_col = self.column_map.get('variant', '')
        grand_total_col = self.column_map.get('grand_total', '')
        fallback_cols = self.platform.date_fallback_columns if (self.platform and self.platform.date_fallback_columns) else []

        summaries = []
        for order_id, group in pending_df.groupby(tax_invoice_col, sort=False):
            first_row = group.iloc[0]

            def _safe(col):
                if col and col in first_row.index:
                    v = str(first_row[col])
                    return '' if v in ('nan', 'NaT') else v
                return ''

            recipient = _safe(recipient_col)
            phone = _safe(phone_col)

            # Best available date from fallback columns (e.g. RTS Time → Paid Time → Created Time)
            best_date = ''
            for col in fallback_cols:
                if col in first_row.index:
                    val = str(first_row[col])
                    if val not in ('nan', 'NaT', ''):
                        best_date = self.format_order_date(val)
                        break

            # Product lines
            products = []
            for _, row in group.iterrows():
                prod = str(row[product_col]) if product_col and product_col in row.index else ''
                if prod in ('nan', 'NaT'):
                    prod = ''
                variant = ''
                if variant_col and variant_col in row.index:
                    v = str(row[variant_col])
                    if v not in ('nan', 'NaT', ''):
                        variant = v
                if variant:
                    prod += f' ({variant})'
                if self.platform and self.platform.implicit_quantity is not None:
                    qty = float(self.platform.implicit_quantity)
                elif qty_col and qty_col in row.index:
                    qty = self.clean_numeric(row[qty_col])
                else:
                    qty = 1.0
                qty_str = str(int(qty)) if qty == int(qty) else str(qty)
                products.append(f"{prod} x{qty_str}")

            grand_total = self.clean_numeric(first_row[grand_total_col]) if grand_total_col and grand_total_col in first_row.index else 0.0

            summaries.append({
                'order_id': str(order_id),
                'recipient': recipient,
                'phone': phone,
                'best_date': best_date,
                'products': products,
                'grand_total': grand_total,
            })

        return summaries

    def group_by_invoice(self, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """Group rows by tax invoice number"""
        tax_invoice_col = self.column_map['tax_invoice']

        df_copy = df.copy()

        # Forward-fill only if platform requires it (fills order_date into blank item rows)
        df_copy = self._forward_fill_invoice_fields(df_copy)

        # Filter out rows with no invoice number
        df_filtered = df_copy[df_copy[tax_invoice_col].notna()]

        # Sort DataFrame by parsed date BEFORE grouping so first-occurrence order in groupby
        # is chronological regardless of date format or pandas version.
        # Uses _parse_sort_key to normalise any format → YYYY-MM-DD HH:MM:SS.
        # Falls back to payment_time when the primary date column (e.g. ship time) is blank
        # — this prevents unshipped January orders from sorting after shipped February orders.
        order_date_col = self.column_map.get('order_date')
        if order_date_col and order_date_col in df_filtered.columns:
            _payment_col = self.column_map.get('payment_time')

            def _row_sort_key(row):
                val = str(row[order_date_col]) if pd.notna(row[order_date_col]) else 'nan'
                sk = self._parse_sort_key(val)
                if not sk and _payment_col and _payment_col in row.index:
                    pay_val = str(row[_payment_col]) if pd.notna(row[_payment_col]) else 'nan'
                    sk = self._parse_sort_key(pay_val)
                return sk or '9999-99-99 99:99:99'

            df_filtered = df_filtered.copy()
            df_filtered['__sort_key__'] = df_filtered.apply(_row_sort_key, axis=1)
            df_filtered = df_filtered.sort_values(by='__sort_key__', kind='stable', na_position='last')
            df_filtered = df_filtered.drop(columns=['__sort_key__'])

        # Group by invoice number preserving df order (sort=False keeps first-occurrence order)
        grouped = {}
        for invoice_num, group in df_filtered.groupby(tax_invoice_col, sort=False):
            key = str(int(invoice_num)) if isinstance(invoice_num, float) and invoice_num == int(invoice_num) else str(invoice_num)
            grouped[key] = group

        return grouped

    def parse_invoice(self, invoice_df: pd.DataFrame, invoice_number: str) -> Invoice:
        """Parse a group of rows into a single Invoice object"""
        first_row = invoice_df.iloc[0]

        # Parse customer info — use assemble_address for multi-field addresses
        customer = Customer(
            name=str(first_row[self.column_map['recipient_name']]),
            address=self.assemble_address(first_row),
            phone=str(first_row[self.column_map['phone']])
        )

        # Parse line items
        items = []
        for _, row in invoice_df.iterrows():
            product_name = str(row[self.column_map['product_name']])
            variant_col = self.column_map.get('variant')
            variant = ''
            if variant_col and variant_col in row.index:
                variant = str(row[variant_col]) if pd.notna(row[variant_col]) else ''

            description = product_name
            if variant and variant != 'nan':
                description += f" ({variant})"

            # Handle implicit quantity (Lazada: each row = 1 item)
            if self.platform and self.platform.implicit_quantity is not None:
                quantity = float(self.platform.implicit_quantity)
            else:
                qty_col = self.column_map.get('quantity')
                if qty_col and qty_col in row.index:
                    quantity = self.clean_numeric(row[qty_col])
                else:
                    quantity = 1.0

            unit_price = self.clean_numeric(row[self.column_map['sale_price']])
            total = quantity * unit_price

            items.append(LineItem(
                description=description,
                quantity=quantity,
                unit_price=unit_price,
                total=total
            ))

        # Calculate totals
        subtotal = sum(item.total for item in items)
        
        # Calculate subtotal_before_discount (sum of all item totals at original price)
        # This is the product amount BEFORE any discounts
        subtotal_before_discount = subtotal
        
        # Calculate discount: use discount_sum_columns if platform specifies them,
        # otherwise fall back to single shopee_discount column from first row
        if self.platform and self.platform.discount_sum_columns:
            discount = 0.0
            for disc_col in self.platform.discount_sum_columns:
                if disc_col in invoice_df.columns:
                    discount += sum(self.clean_numeric(row[disc_col]) for _, row in invoice_df.iterrows())
        else:
            discount_col = self.column_map.get('shopee_discount')
            discount = self.clean_numeric(first_row[discount_col]) if discount_col and discount_col in first_row.index else 0.0

        # Calculate subtotal_after_discount (product amount after discount, before shipping)
        subtotal_after_discount = subtotal_before_discount - discount

        shipping_col = self.column_map.get('shipping_buyer')
        if shipping_col and shipping_col in invoice_df.columns:
            # Sum shipping across all rows (for platforms like Lazada where each row has its own shipping)
            if self.platform and not self.platform.needs_forward_fill:
                shipping = sum(self.clean_numeric(row[shipping_col]) for _, row in invoice_df.iterrows())
            else:
                # Shopee: shipping is invoice-level (forward-filled), just read first row
                shipping = self.clean_numeric(first_row[shipping_col])
        else:
            shipping = 0.0

        service_col = self.column_map.get('service_fee')
        service_fee = self.clean_numeric(first_row[service_col]) if service_col and service_col in first_row.index else 0.0

        # รวมจํานวนเงิน = sum(จํานวนเงิน all items) - ส่วนลด + ค่าขนส่ง
        grand_total = subtotal - discount + shipping

        # Extract order date, order ID, and tracking info
        raw_date_val = str(first_row[self.column_map['order_date']])
        # When ship time is blank (e.g. unshipped Shopee orders), fall back to payment time.
        # Without this, NaN ship dates sort to the end (bill 9999…) causing Feb orders
        # with valid ship dates to receive lower bill numbers than Jan orders.
        if raw_date_val in ('nan', 'NaT', ''):
            payment_col = self.column_map.get('payment_time')
            if payment_col and payment_col in first_row.index:
                pay_val = str(first_row[payment_col])
                if pay_val not in ('nan', 'NaT', ''):
                    raw_date_val = pay_val
        # Try platform date_fallback_columns (e.g. TikTok: RTS Time → Paid Time → Created Time)
        if raw_date_val in ('nan', 'NaT', '') and self.platform and self.platform.date_fallback_columns:
            for fb_col in self.platform.date_fallback_columns:
                if fb_col in first_row.index:
                    fb_val = str(first_row[fb_col])
                    if fb_val not in ('nan', 'NaT', ''):
                        raw_date_val = fb_val
                        break
        order_date = self.format_order_date(raw_date_val)
        order_sort_key = self._parse_sort_key(raw_date_val)  # full datetime, trimmed only at display
        order_id_raw = first_row[self.column_map['order_id']] if 'order_id' in self.column_map else ''
        order_id = str(int(order_id_raw)) if isinstance(order_id_raw, float) and order_id_raw == int(order_id_raw) else str(order_id_raw)

        tracking_col = self.column_map.get('tracking_number')
        tracking_number = ''
        if tracking_col and tracking_col in first_row.index and pd.notna(first_row[tracking_col]):
            tracking_number = str(first_row[tracking_col])

        invoice = Invoice(
            invoice_number=invoice_number,
            order_id=order_id,
            bill_number="",
            order_date=order_date,
            tracking_number=tracking_number,
            customer=customer,
            items=items,
            subtotal=subtotal,
            discount=discount,
            shipping=shipping,
            service_fee=service_fee,
            vat_rate=self.vat_rate,
            grand_total=grand_total,
            order_sort_key=order_sort_key,
            subtotal_before_discount=subtotal_before_discount,
            subtotal_after_discount=subtotal_after_discount,
        )
        invoice.compute_vat()
        return invoice

    def parse_csv_to_invoices(self, file_path: str) -> List[Invoice]:
        """Main function: Read CSV and return list of Invoice objects"""
        df = self.read_csv(file_path)

        valid, errors = self.validate_csv(df)
        if not valid:
            raise ValueError(f"CSV validation failed: {', '.join(errors)}")

        df, cancelled_count = self.filter_cancelled_invoices(df)
        self.last_cancelled_count = cancelled_count
        if cancelled_count > 0:
            print(f"Filtered out {cancelled_count} cancelled invoice(s)")

        grouped = self.group_by_invoice(df)

        invoices = []
        for invoice_num, invoice_df in grouped.items():
            try:
                invoice = self.parse_invoice(invoice_df, invoice_num)
                invoices.append(invoice)
            except Exception as e:
                print(f"Warning: Failed to parse invoice {invoice_num}: {e}")
                continue

        return invoices
