"""
Turns a filtered DataFrame into Invoice/LineItem/Customer domain objects
(src/bill_data.py): grouping rows by invoice number, sorting invoices
chronologically, and building each Invoice's totals/VAT. This is the only
module that constructs domain objects — csv_io.py and order_filters.py
work purely in dataframes, and normalize.py has no notion of an invoice.
"""
from typing import Dict

import pandas as pd

from ..bill_data import Customer, Invoice, LineItem
from .csv_io import read_csv, validate_csv
from .normalize import assemble_address, clean_address, clean_numeric, format_order_date, parse_sort_key
from .order_filters import _forward_fill_invoice_fields, filter_cancelled_invoices, filter_preorders


def group_by_invoice(context, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Group rows by tax invoice number"""
    tax_invoice_col = context.column_map['tax_invoice']

    df_copy = df.copy()

    # Forward-fill only if platform requires it (fills order_date into blank item rows)
    df_copy = _forward_fill_invoice_fields(context, df_copy)

    # Filter out rows with no invoice number
    df_filtered = df_copy[df_copy[tax_invoice_col].notna()]

    # Sort DataFrame by parsed date BEFORE grouping so first-occurrence order in groupby
    # is chronological regardless of date format or pandas version.
    # Uses parse_sort_key to normalise any format → YYYY-MM-DD HH:MM:SS.
    # Falls back to payment_time when the primary date column (e.g. ship time) is blank
    # — this prevents unshipped January orders from sorting after shipped February orders.
    order_date_col = context.column_map.get('order_date')
    if order_date_col and order_date_col in df_filtered.columns:
        _payment_col = context.column_map.get('payment_time')

        def _row_sort_key(row):
            val = str(row[order_date_col]) if pd.notna(row[order_date_col]) else 'nan'
            sk = parse_sort_key(val, context)
            if not sk and _payment_col and _payment_col in row.index:
                pay_val = str(row[_payment_col]) if pd.notna(row[_payment_col]) else 'nan'
                sk = parse_sort_key(pay_val, context)
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


def parse_invoice(context, invoice_df: pd.DataFrame, invoice_number: str) -> Invoice:
    """Parse a group of rows into a single Invoice object"""
    column_map = context.column_map
    platform = context.platform
    first_row = invoice_df.iloc[0]

    # Parse customer info — use assemble_address for multi-field addresses
    customer = Customer(
        name=str(first_row[column_map['recipient_name']]),
        address=assemble_address(first_row, context),
        phone=str(first_row[column_map['phone']])
    )

    # Parse line items
    items = []
    for _, row in invoice_df.iterrows():
        product_name = str(row[column_map['product_name']])

        # Defensive guard: skip rows that are neither real items nor
        # description rows already caught upstream — e.g. leftover
        # all-blank rows whose forward-filled order_id makes them look
        # like a legitimate 2nd+ item row. Only skip when BOTH the
        # product name is empty/NaN AND the quantity is empty/zero, so
        # we never drop a genuine item that merely has qty 0.
        name_is_blank = pd.isna(row[column_map['product_name']]) or product_name.strip() in ('', 'nan')
        if name_is_blank:
            qty_col = column_map.get('quantity')
            if platform and platform.implicit_quantity is not None:
                # Lazada-style: no real quantity column to check; blank
                # product name alone is enough to treat as empty.
                qty_is_blank = True
            elif qty_col and qty_col in row.index:
                raw_qty = row[qty_col]
                qty_is_blank = pd.isna(raw_qty) or str(raw_qty).strip() in ('', 'nan') or clean_numeric(raw_qty) == 0
            else:
                qty_is_blank = True
            if qty_is_blank:
                continue

        variant_col = column_map.get('variant')
        variant = ''
        if variant_col and variant_col in row.index:
            variant = str(row[variant_col]) if pd.notna(row[variant_col]) else ''

        description = product_name
        if variant and variant != 'nan':
            description += f" ({variant})"

        # Handle implicit quantity (Lazada: each row = 1 item)
        if platform and platform.implicit_quantity is not None:
            quantity = float(platform.implicit_quantity)
        else:
            qty_col = column_map.get('quantity')
            if qty_col and qty_col in row.index:
                quantity = clean_numeric(row[qty_col])
            else:
                quantity = 1.0

        unit_price = clean_numeric(row[column_map['sale_price']])
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
    # otherwise fall back to single shopee_discount column from first row.
    # abs() handles platforms like Lazada where discounts are negative values.
    if platform and platform.discount_sum_columns:
        discount = 0.0
        for disc_col in platform.discount_sum_columns:
            if disc_col in invoice_df.columns:
                discount += sum(clean_numeric(row[disc_col]) for _, row in invoice_df.iterrows())
    else:
        discount_col = column_map.get('shopee_discount')
        discount = clean_numeric(first_row[discount_col]) if discount_col and discount_col in first_row.index else 0.0
    discount = abs(discount)

    # Calculate subtotal_after_discount (product amount after discount, before shipping)
    subtotal_after_discount = subtotal_before_discount - discount

    shipping_col = column_map.get('shipping_buyer')
    if shipping_col and shipping_col in invoice_df.columns:
        # Sum shipping across all rows (for platforms like Lazada where each row has its own shipping)
        if platform and not platform.needs_forward_fill:
            shipping = sum(clean_numeric(row[shipping_col]) for _, row in invoice_df.iterrows())
        else:
            # Shopee: shipping is invoice-level (forward-filled), just read first row
            shipping = clean_numeric(first_row[shipping_col])
    else:
        shipping = 0.0

    service_col = column_map.get('service_fee')
    service_fee = clean_numeric(first_row[service_col]) if service_col and service_col in first_row.index else 0.0

    # รวมจํานวนเงิน = sum(จํานวนเงิน all items) - ส่วนลด + ค่าขนส่ง
    grand_total = subtotal - discount + shipping

    # Extract order date, order ID, and tracking info
    raw_date_val = str(first_row[column_map['order_date']])
    # When ship time is blank (e.g. unshipped Shopee orders), fall back to payment time.
    # Without this, NaN ship dates sort to the end (bill 9999…) causing Feb orders
    # with valid ship dates to receive lower bill numbers than Jan orders.
    if raw_date_val in ('nan', 'NaT', ''):
        payment_col = column_map.get('payment_time')
        if payment_col and payment_col in first_row.index:
            pay_val = str(first_row[payment_col])
            if pay_val not in ('nan', 'NaT', ''):
                raw_date_val = pay_val
    # Try platform date_fallback_columns (e.g. TikTok: RTS Time → Paid Time → Created Time)
    if raw_date_val in ('nan', 'NaT', '') and platform and platform.date_fallback_columns:
        for fb_col in platform.date_fallback_columns:
            if fb_col in first_row.index:
                fb_val = str(first_row[fb_col])
                if fb_val not in ('nan', 'NaT', ''):
                    raw_date_val = fb_val
                    break
    order_date = format_order_date(raw_date_val, context)
    order_sort_key = parse_sort_key(raw_date_val, context)  # full datetime, trimmed only at display
    order_id_raw = first_row[column_map['order_id']] if 'order_id' in column_map else ''
    order_id = str(int(order_id_raw)) if isinstance(order_id_raw, float) and order_id_raw == int(order_id_raw) else clean_address(str(order_id_raw))

    tracking_col = column_map.get('tracking_number')
    tracking_number = ''
    if tracking_col and tracking_col in first_row.index and pd.notna(first_row[tracking_col]):
        tracking_number = clean_address(str(first_row[tracking_col]))

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
        vat_rate=context.vat_rate,
        grand_total=grand_total,
        order_sort_key=order_sort_key,
        subtotal_before_discount=subtotal_before_discount,
        subtotal_after_discount=subtotal_after_discount,
    )
    invoice.compute_vat()
    return invoice


def parse_csv_to_invoices(context, file_path: str):
    """Main function: Read CSV and return (invoices, cancelled_count, preorder_count).

    The facade (CSVParser.parse_csv_to_invoices) unpacks this and additionally
    records last_cancelled_count/last_preorder_count for backward compatibility.
    """
    df, _ = read_csv(context, file_path)

    valid, errors = validate_csv(context, df)
    if not valid:
        raise ValueError(f"CSV validation failed: {', '.join(errors)}")

    df, cancelled_count = filter_cancelled_invoices(context, df)
    if cancelled_count > 0:
        print(f"Filtered out {cancelled_count} cancelled invoice(s)")

    df, preorder_count = filter_preorders(context, df)
    if preorder_count > 0:
        print(f"Filtered out {preorder_count} pre-order row(s)")

    grouped = group_by_invoice(context, df)

    invoices = []
    for invoice_num, invoice_df in grouped.items():
        try:
            invoice = parse_invoice(context, invoice_df, invoice_num)
            invoices.append(invoice)
        except Exception as e:
            print(f"Warning: Failed to parse invoice {invoice_num}: {e}")
            continue

    return invoices, cancelled_count, preorder_count
