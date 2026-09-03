"""
Row/invoice-level filtering and status-driven decisions: cancelled orders,
pre-orders, confirmed returns, pending (unshipped) orders, and the
forward-fill of invoice-level fields those filters depend on. Everything
here takes (context, df) and returns a filtered/annotated dataframe (or a
summary derived from one) — it never builds Invoice/LineItem objects
(assembly.py) and never touches individual cell formatting (normalize.py).
"""
from typing import List, Tuple

import pandas as pd

from ..platform_presets import SHOPEE_PRESET
from .normalize import clean_numeric, format_order_date


def _get_cancelled_statuses(context) -> list:
    """Get cancelled statuses from platform or defaults"""
    if context.platform:
        return context.platform.cancelled_statuses
    return SHOPEE_PRESET.cancelled_statuses


def _get_confirmed_return_statuses(context) -> list:
    """Get confirmed return statuses from platform or defaults"""
    if context.platform:
        return context.platform.confirmed_return_statuses
    return SHOPEE_PRESET.confirmed_return_statuses


def _needs_forward_fill(context) -> bool:
    """Check if platform needs forward-fill for invoice-level fields"""
    if context.platform:
        return context.platform.needs_forward_fill
    return True  # default (Shopee behavior)


def _get_invoice_level_fields(context) -> list:
    """Get list of invoice-level field keys for forward-fill"""
    if context.platform and context.platform.invoice_level_fields:
        return context.platform.invoice_level_fields
    # Default (Shopee)
    return [
        'order_id', 'tax_invoice', 'order_date', 'recipient_name',
        'phone', 'address', 'tracking_number', 'shopee_discount',
        'shipping_buyer', 'service_fee', 'grand_total', 'estimated_shipping',
    ]


def _forward_fill_invoice_fields(context, df: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill invoice-level fields if platform requires it"""
    if not _needs_forward_fill(context):
        return df

    for field_key in _get_invoice_level_fields(context):
        col = context.column_map.get(field_key)
        if col and col in df.columns:
            df[col] = df[col].replace('', pd.NA)
            df[col] = df[col].ffill()
    return df


def filter_cancelled_invoices(context, df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """Filter out entire invoices where any row has a cancelled status.

    Returns the filtered DataFrame and count of removed invoices.
    """
    status_col = context.column_map.get('order_status')
    order_col = context.column_map['order_id']

    if not status_col or status_col not in df.columns:
        return df, 0

    # For Shopee-style CSVs (needs_forward_fill=True), the 2nd+ item rows of
    # each order have a blank order_id. Forward-fill order_id first so those
    # rows are correctly identified as belonging to the cancelled order.
    df = df.copy()
    if _needs_forward_fill(context) and order_col in df.columns:
        df[order_col] = df[order_col].replace('', pd.NA).ffill()

    cancelled_statuses = _get_cancelled_statuses(context)
    cancelled_mask = df[status_col].astype(str).str.strip().isin(cancelled_statuses)
    cancelled_order_ids = df.loc[cancelled_mask, order_col].unique()

    if len(cancelled_order_ids) == 0:
        return df, 0

    df_filtered = df[~df[order_col].isin(cancelled_order_ids)]
    return df_filtered, len(cancelled_order_ids)


def filter_preorders(context, df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """Keep only orders whose order_type is explicitly in platform.normal_values.

    TikTok marks order type ('Normal' / 'Pre-order') only on the first SKU row
    of an order; later rows are blank. We therefore look at each order_id and
    keep it only if at least one of its rows is explicitly 'Normal'. Orders
    where every row is blank or 'Pre-order' are removed entirely.

    No-op when the platform doesn't define preorder_values (used here as the
    feature flag) or the column is absent (older TikTok exports lack it).
    Returns (filtered_df, removed_order_count).
    """
    if not context.platform or not context.platform.preorder_values:
        return df, 0

    type_col = context.column_map.get('order_type')
    order_col = context.column_map.get('order_id')
    if not type_col or type_col not in df.columns:
        return df, 0
    if not order_col or order_col not in df.columns:
        return df, 0

    normalized = df[type_col].astype(str).str.strip()
    normal_mask = normalized == 'Normal'
    normal_order_ids = set(df.loc[normal_mask, order_col].unique())
    all_order_ids = set(df[order_col].unique())
    removed_ids = all_order_ids - normal_order_ids
    if not removed_ids:
        return df, 0

    df_filtered = df[df[order_col].isin(normal_order_ids)].copy()
    return df_filtered, len(removed_ids)


def filter_confirmed_returns(context, df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """Auto-remove item rows with confirmed return status.

    For Shopee-style CSVs (needs_forward_fill=True), invoice-level fields
    (customer name, address, order_id, etc.) are forward-filled FIRST so that
    order-level info is preserved even when the returned item is in the first
    row of the order (row1 also carries the customer/address data).

    Returns (filtered_df, removed_item_count).
    """
    if context.platform and context.platform.return_status_field is None:
        return df, 0

    return_col_key = 'return_status'
    if context.platform and context.platform.return_status_field:
        return_col_key = context.platform.return_status_field

    return_col = context.column_map.get(return_col_key)
    if not return_col or return_col not in df.columns:
        return df, 0

    confirmed_statuses = _get_confirmed_return_statuses(context)
    if not confirmed_statuses:
        return df, 0

    # Forward-fill invoice-level fields first so that if the returned item is
    # in row1, its order-level info (customer, address, order_id, etc.) is
    # propagated to the remaining item rows before that row is deleted.
    df = _forward_fill_invoice_fields(context, df.copy())

    return_mask = df[return_col].astype(str).str.strip().isin(confirmed_statuses)
    rows_to_drop = df.index[return_mask].tolist()

    if not rows_to_drop:
        return df, 0

    df_filtered = df.drop(index=rows_to_drop)
    return df_filtered, len(rows_to_drop)


def detect_return_items(context, df: pd.DataFrame) -> List[dict]:
    """Detect rows with return/refund statuses.

    Returns a list of flagged items with their details and category:
    - 'confirmed': status is in confirmed return statuses
    - 'unknown': non-blank status not in confirmed list
    """
    # If platform explicitly has no return column, skip
    if context.platform and context.platform.return_status_field is None:
        return []

    return_col_key = 'return_status'
    if context.platform and context.platform.return_status_field:
        return_col_key = context.platform.return_status_field

    return_col = context.column_map.get(return_col_key)
    if not return_col or return_col not in df.columns:
        return []

    order_col = context.column_map['order_id']
    product_col = context.column_map['product_name']
    variant_col = context.column_map.get('variant')

    confirmed_statuses = _get_confirmed_return_statuses(context)

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


def apply_return_decisions(context, df: pd.DataFrame, decisions: List[dict]) -> pd.DataFrame:
    """Apply user decisions about return items.

    Each decision dict has:
    - row_index: the DataFrame row index
    - action: 'keep' | 'remove_product' | 'remove_bill'
    """
    order_col = context.column_map['order_id']

    # Forward-fill if needed so we can correctly identify invoice grouping
    df = _forward_fill_invoice_fields(context, df)

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


def split_pending_orders(context, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Split df into (shipped_df, pending_df) based on primary date column being NaN.

    Only applies to platforms with date_fallback_columns (e.g. TikTok: Shipped Time can be NaN).
    Pending orders are excluded from bills/sales report and shown on a separate summary page.
    Returns (shipped_df, pending_df); pending_df is empty if platform has no fallback columns.
    """
    if not (context.platform and context.platform.date_fallback_columns):
        return df, pd.DataFrame(columns=df.columns)

    order_date_col = context.column_map.get('order_date')
    if not order_date_col or order_date_col not in df.columns:
        return df, pd.DataFrame(columns=df.columns)

    tax_invoice_col = context.column_map.get('tax_invoice', context.column_map.get('order_id'))
    date_is_nan = df[order_date_col].isna() | (df[order_date_col].astype(str).str.strip().isin(['nan', 'NaT', '']))
    pending_ids = df.loc[date_is_nan, tax_invoice_col].dropna().unique()

    if len(pending_ids) == 0:
        return df, pd.DataFrame(columns=df.columns)

    # For platforms with shipped_statuses: orders with a "shipped" status should always
    # get a bill even if their primary date column (e.g. Shipped Time) is NaN.
    # This covers TikTok orders with substatus "อยู่ระหว่างขนส่ง" that lack Shipped Time.
    shipped_statuses = getattr(context.platform, 'shipped_statuses', []) if context.platform else []
    status_col = context.column_map.get('order_status')
    if shipped_statuses and status_col and status_col in df.columns:
        shipped_mask = df[status_col].astype(str).str.strip().isin(shipped_statuses)
        shipped_order_ids = set(df.loc[shipped_mask, tax_invoice_col].dropna().unique())
        pending_ids = [oid for oid in pending_ids if oid not in shipped_order_ids]

    if len(pending_ids) == 0:
        return df, pd.DataFrame(columns=df.columns)

    shipped_df = df[~df[tax_invoice_col].isin(pending_ids)].copy()
    pending_df = df[df[tax_invoice_col].isin(pending_ids)].copy()
    return shipped_df, pending_df


def get_pending_summary(context, pending_df: pd.DataFrame) -> list:
    """Extract summary rows from pending (unshipped) orders for the summary page."""
    if pending_df.empty:
        return []

    tax_invoice_col = context.column_map.get('tax_invoice', context.column_map.get('order_id'))
    recipient_col = context.column_map.get('recipient_name', '')
    phone_col = context.column_map.get('phone', '')
    product_col = context.column_map.get('product_name', '')
    qty_col = context.column_map.get('quantity', '')
    variant_col = context.column_map.get('variant', '')
    grand_total_col = context.column_map.get('grand_total', '')
    fallback_cols = context.platform.date_fallback_columns if (context.platform and context.platform.date_fallback_columns) else []

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
                    best_date = format_order_date(val, context)
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
            if context.platform and context.platform.implicit_quantity is not None:
                qty = float(context.platform.implicit_quantity)
            elif qty_col and qty_col in row.index:
                qty = clean_numeric(row[qty_col])
            else:
                qty = 1.0
            qty_str = str(int(qty)) if qty == int(qty) else str(qty)
            products.append(f"{prod} x{qty_str}")

        grand_total = clean_numeric(first_row[grand_total_col]) if grand_total_col and grand_total_col in first_row.index else 0.0

        summaries.append({
            'order_id': str(order_id),
            'recipient': recipient,
            'phone': phone,
            'best_date': best_date,
            'products': products,
            'grand_total': grand_total,
        })

    return summaries
