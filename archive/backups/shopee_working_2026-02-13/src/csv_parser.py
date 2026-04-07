"""
CSV Parser for Shopee export files
"""
import pandas as pd
from typing import Dict, List, Tuple
from .bill_data import Invoice, Customer, LineItem


class CSVParser:
    """Parse and validate Shopee CSV files"""
    
    # Column name mapping (Thai -> English keys)
    # Updated for new Shopee format (2026+) - no spaces around column names
    COLUMN_MAP = {
        'order_id': 'หมายเลขคำสั่งซื้อ',
        'buyer_username': 'ชื่อผู้ใช้ (ผู้ซื้อ)',
        'order_date': 'วันที่ทำการสั่งซื้อ',
        'payment_time': 'เวลาการชำระสินค้า',
        'product_name': 'ชื่อสินค้า',
        'sale_price': 'ราคาขาย',
        'quantity': 'จำนวน',
        'total': 'ราคาขายสุทธิ',
        'shipping_buyer': 'ค่าจัดส่งที่ชำระโดยผู้ซื้อ',
        'service_fee': 'ค่าบริการ',
        'grand_total': 'จำนวนเงินทั้งหมด',
        'estimated_shipping': 'ค่าจัดส่งโดยประมาณ',
        'recipient_name': 'ชื่อผู้รับ',
        'phone': 'หมายเลขโทรศัพท์',
        'address': 'ที่อยู่ในการจัดส่ง',
        'tracking_number': '*หมายเลขติดตามพัสดุ',
        'payment_method': 'ช่องทางการชำระเงิน',
        'shipping_time': 'เวลาส่งสินค้า',
        'shopee_discount': 'ส่วนลดจาก Shopee',
        'variant': 'ชื่อตัวเลือก',
        'tax_invoice': 'หมายเลขคำสั่งซื้อ',  # New format uses order_id as grouping key
        'order_status': 'สถานะการสั่งซื้อ',
        'return_status': 'สถานะการคืนเงินหรือคืนสินค้า'
    }

    # Statuses that indicate a cancelled order - entire invoice should be excluded
    CANCELLED_STATUSES = ['ยกเลิกแล้ว']

    # Return status: confirmed return
    CONFIRMED_RETURN_STATUSES = ['คำขอได้รับการยอมรับแล้ว']

    # Required fields that must be mapped
    REQUIRED_FIELDS = [
        'order_id',
        'product_name',
        'recipient_name',
        'address',
        'phone'
    ]
    
    def __init__(self, vat_rate: float = 0.07, custom_column_map: dict = None):
        self.vat_rate = vat_rate
        # Use custom mapping if provided, otherwise use default
        if custom_column_map:
            # Strip whitespace from mapping values for compatibility
            self.column_map = {k: v.strip() for k, v in custom_column_map.items()}
        else:
            self.column_map = self.COLUMN_MAP.copy()
    
    def detect_columns(self, file_path: str) -> List[str]:
        """Detect all columns in the CSV file"""
        df = self.read_csv(file_path)
        return list(df.columns)
    
    def get_field_definitions(self) -> dict:
        """Return field definitions for UI"""
        return {
            'tax_invoice': 'Tax Invoice Number (เลขที่ใบกำกับ)',
            'order_id': 'Order Number (หมายเลขคำสั่งซื้อ)',
            'order_date': 'Order Date (วันที่ทำการสั่งซื้อ)',
            'product_name': 'Product Name (ชื่อสินค้า) *Required',
            'variant': 'Product Variant (ชื่อตัวเลือก)',
            'quantity': 'Quantity (จำนวน)',
            'sale_price': 'Unit Price (ราคาขาย)',
            'total': 'Line Total (รวม)',
            'recipient_name': 'Customer Name (ชื่อผู้รับ) *Required',
            'phone': 'Phone Number (หมายเลขโทรศัพท์) *Required',
            'address': 'Address (ที่อยู่ในการจัดส่ง) *Required',
            'tracking_number': 'Tracking Number (หมายเลขติดตามพัสดุ)',
            'shopee_discount': 'Discount (ส่วนลดจาก Shopee)',
            'shipping_buyer': 'Shipping Fee (ค่าจัดส่ง)',
            'service_fee': 'Service Fee (ค่าบริการ)',
            'grand_total': 'Grand Total (จำนวนเงินทั้งหมด)'
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
        """Read CSV file with proper encoding"""
        try:
            df = pd.read_csv(file_path, encoding='utf-8')
        except UnicodeDecodeError:
            # Try other encodings
            df = pd.read_csv(file_path, encoding='tis-620')

        # Strip whitespace from column names (handles both old/new Shopee formats)
        df.columns = [col.strip().lstrip('\ufeff') for col in df.columns]

        # Flag if first column is not the expected order ID column
        first_col = df.columns[0] if len(df.columns) > 0 else ''
        if first_col != 'หมายเลขคำสั่งซื้อ':
            print(f"WARNING: First column is '{first_col}', expected 'หมายเลขคำสั่งซื้อ'. CSV file may be corrupted.")
            self.first_column_warning = f"First column is '{first_col}' instead of 'หมายเลขคำสั่งซื้อ'. The CSV file may be corrupted — please re-export from Shopee."
        else:
            self.first_column_warning = None

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
        
        # Get detected columns
        detected_cols = set(df.columns)
        expected_cols = set(self.column_map.values())
        
        # Check for missing required columns
        required_fields = ['order_id', 'product_name', 'recipient_name', 'address', 'phone']
        for field in required_fields:
            col_name = self.column_map.get(field, '')
            if col_name and col_name not in detected_cols:
                result['missing_columns'].append({
                    'field': field,
                    'expected_name': col_name
                })
                result['errors'].append(
                    f"❌ Required column missing: '{col_name}' (used for {field})"
                )
        
        # Check for extra columns (might indicate format change)
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
            
            result['errors'].insert(0, 
                f"🚨 CSV FORMAT CHANGED: {missing_count} required column(s) not found!"
            )
            result['errors'].append(
                "\n💡 This usually happens when Shopee updates their export format."
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
    
    def clean_numeric(self, value) -> float:
        """Clean and convert numeric values"""
        if pd.isna(value) or value == '' or value == '-':
            return 0.0
        
        # Remove spaces and convert
        if isinstance(value, str):
            value = value.strip().replace(',', '').replace(' ', '')
            if value == '' or value == '-':
                return 0.0
        
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0
    
    def filter_cancelled_invoices(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
        """Filter out entire invoices where any row has a cancelled status.

        Returns the filtered DataFrame and count of removed invoices.
        """
        status_col = self.column_map.get('order_status', 'สถานะการสั่งซื้อ')
        order_col = self.column_map['order_id']

        if status_col not in df.columns:
            return df, 0

        # Find order IDs where ANY row has a cancelled status
        cancelled_mask = df[status_col].astype(str).str.strip().isin(self.CANCELLED_STATUSES)
        cancelled_order_ids = df.loc[cancelled_mask, order_col].unique()

        if len(cancelled_order_ids) == 0:
            return df, 0

        # Remove ALL rows belonging to those order IDs
        df_filtered = df[~df[order_col].isin(cancelled_order_ids)]
        return df_filtered, len(cancelled_order_ids)

    def detect_return_items(self, df: pd.DataFrame) -> List[dict]:
        """Detect rows with return/refund statuses.

        Returns a list of flagged items with their details and category:
        - 'confirmed': status is in CONFIRMED_RETURN_STATUSES
        - 'unknown': non-blank status not in confirmed list
        """
        return_col = self.column_map.get('return_status', 'สถานะการคืนเงินหรือคืนสินค้า')
        order_col = self.column_map['order_id']
        product_col = self.column_map['product_name']
        variant_col = self.column_map['variant']

        if return_col not in df.columns:
            return []

        flagged = []
        for idx, row in df.iterrows():
            status = str(row[return_col]).strip() if pd.notna(row[return_col]) else ''
            if status == '' or status == 'nan':
                continue

            order_id = str(row[order_col])
            product = str(row[product_col])
            variant = str(row[variant_col]) if pd.notna(row[variant_col]) else ''

            category = 'confirmed' if status in self.CONFIRMED_RETURN_STATUSES else 'unknown'

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

        # Forward-fill invoice-level fields FIRST so we can correctly identify
        # which rows belong to which invoice. In Shopee CSV, only the first row
        # of a multi-item invoice has order_id/customer data; subsequent rows are blank.
        invoice_level_fields = [
            'order_id', 'tax_invoice', 'order_date', 'recipient_name',
            'phone', 'address', 'tracking_number', 'shopee_discount',
            'shipping_buyer', 'service_fee', 'grand_total'
        ]
        for field in invoice_level_fields:
            col = self.column_map.get(field)
            if col and col in df.columns:
                df[col] = df[col].replace('', pd.NA)
                df[col] = df[col].ffill()

        rows_to_drop = set()
        orders_to_drop = set()

        for decision in decisions:
            action = decision.get('action', 'keep')
            row_idx = decision.get('row_index')

            if action == 'remove_product' and row_idx is not None:
                rows_to_drop.add(row_idx)
            elif action == 'remove_bill' and row_idx is not None:
                # Find the order_id for this row and mark all its rows for removal
                if row_idx in df.index:
                    order_id = df.loc[row_idx, order_col]
                    orders_to_drop.add(order_id)

        # Remove entire orders first
        if orders_to_drop:
            df = df[~df[order_col].isin(orders_to_drop)]

        # Remove individual product rows
        if rows_to_drop:
            df = df.drop(index=[i for i in rows_to_drop if i in df.index])

        return df

    def group_by_invoice(self, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """Group rows by tax invoice number"""
        tax_invoice_col = self.column_map['tax_invoice']
        
        # Make a copy to avoid modifying original
        df_copy = df.copy()
        
        # Forward-fill blank invoice-level fields (blank means same invoice as row above)
        # These fields are typically blank for additional line items in the same invoice
        invoice_level_fields = [
            'tax_invoice',
            'order_id',
            'order_date',
            'recipient_name',
            'phone',
            'address',
            'tracking_number',
            'shopee_discount',
            'shipping_buyer',
            'service_fee',
            'grand_total'
        ]
        
        for field in invoice_level_fields:
            if field in self.column_map:
                col_name = self.column_map[field]
                # Replace empty strings with NaN, then forward fill
                df_copy[col_name] = df_copy[col_name].replace('', pd.NA)
                df_copy[col_name] = df_copy[col_name].ffill()  # Use ffill() instead of deprecated fillna(method='ffill')
        
        # Now filter out rows that still have no invoice number
        df_filtered = df_copy[df_copy[tax_invoice_col].notna()]
        
        # Group by invoice number (fix float→string conversion for numeric IDs)
        grouped = {}
        for invoice_num, group in df_filtered.groupby(tax_invoice_col):
            key = str(int(invoice_num)) if isinstance(invoice_num, float) and invoice_num == int(invoice_num) else str(invoice_num)
            grouped[key] = group
        
        return grouped
    
    def parse_invoice(self, invoice_df: pd.DataFrame, invoice_number: str) -> Invoice:
        """Parse a group of rows into a single Invoice object"""
        # Get first row for order-level info (same across all rows)
        first_row = invoice_df.iloc[0]
        
        # Parse customer info
        customer = Customer(
            name=str(first_row[self.column_map['recipient_name']]),
            address=str(first_row[self.column_map['address']]),
            phone=str(first_row[self.column_map['phone']])
        )
        
        # Parse line items
        items = []
        for _, row in invoice_df.iterrows():
            product_name = str(row[self.column_map['product_name']])
            variant = str(row[self.column_map['variant']]) if pd.notna(row[self.column_map['variant']]) else ''
            
            # Combine product name and variant
            description = product_name
            if variant and variant != 'nan':
                description += f" ({variant})"
            
            quantity = self.clean_numeric(row[self.column_map['quantity']])
            unit_price = self.clean_numeric(row[self.column_map['sale_price']])
            total = self.clean_numeric(row[self.column_map['total']])
            
            items.append(LineItem(
                description=description,
                quantity=quantity,
                unit_price=unit_price,
                total=total
            ))
        
        # Calculate totals
        subtotal = sum(item.total for item in items)
        discount = self.clean_numeric(first_row[self.column_map['shopee_discount']])
        
        # Shipping fee - use the buyer-paid amount
        shipping = self.clean_numeric(first_row[self.column_map['shipping_buyer']])
        
        service_fee = self.clean_numeric(first_row[self.column_map['service_fee']])
        grand_total = self.clean_numeric(first_row[self.column_map['grand_total']])
        
        # Extract order date, order ID, and tracking info
        order_date = str(first_row[self.column_map['order_date']])
        # Convert order_id to string, removing trailing .0 from float conversion
        order_id_raw = first_row[self.column_map['order_id']] if 'order_id' in self.column_map else ''
        order_id = str(int(order_id_raw)) if isinstance(order_id_raw, float) and order_id_raw == int(order_id_raw) else str(order_id_raw)
        tracking_number = str(first_row[self.column_map['tracking_number']]) if pd.notna(first_row[self.column_map['tracking_number']]) else ''
        
        
        invoice = Invoice(
            invoice_number=invoice_number,
            order_id=order_id,
            bill_number="",  # Will be assigned during PDF generation
            order_date=order_date,
            tracking_number=tracking_number,
            customer=customer,
            items=items,
            subtotal=subtotal,
            discount=discount,
            shipping=shipping,
            service_fee=service_fee,
            vat_rate=self.vat_rate,
            grand_total=grand_total
        )
        invoice.compute_vat()
        return invoice
    
    def parse_csv_to_invoices(self, file_path: str) -> List[Invoice]:
        """Main function: Read CSV and return list of Invoice objects"""
        # Read CSV
        df = self.read_csv(file_path)

        # Validate
        valid, errors = self.validate_csv(df)
        if not valid:
            raise ValueError(f"CSV validation failed: {', '.join(errors)}")

        # Filter out cancelled invoices
        df, cancelled_count = self.filter_cancelled_invoices(df)
        self.last_cancelled_count = cancelled_count
        if cancelled_count > 0:
            print(f"Filtered out {cancelled_count} cancelled invoice(s)")

        # Group by invoice
        grouped = self.group_by_invoice(df)
        
        # Parse each invoice
        invoices = []
        for invoice_num, invoice_df in grouped.items():
            try:
                invoice = self.parse_invoice(invoice_df, invoice_num)
                invoices.append(invoice)
            except Exception as e:
                print(f"Warning: Failed to parse invoice {invoice_num}: {e}")
                continue
        
        return invoices
