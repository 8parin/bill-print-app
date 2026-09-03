"""Shared CSV processing pipeline used by /save-mapping and /apply-return-decisions.

Both routes used to re-implement the same sequence of steps independently:
read_csv -> filter_cancelled_invoices -> filter_preorders ->
filter_confirmed_returns -> [return-decision handling] -> split_pending_orders
-> get_pending_summary -> build trimmed df -> group_by_invoice -> parse_invoice
loop -> sort by order_sort_key -> stamp order_index -> stamp __bill_order__
column onto the trimmed df.

process_csv() runs that pipeline once so both routes share one implementation.

DELIBERATE FIX: forward-fill (parser._forward_fill_invoice_fields) is now
ALWAYS applied to the trimmed df, regardless of whether return decisions were
supplied. Previously only the /save-mapping path applied it. This is a no-op
for platforms where needs_forward_fill is False (Lazada, TikTok), and
idempotent for Shopee (filter_confirmed_returns already forward-fills before
deleting rows), so it does not change golden values.
"""
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from src.debug_util import debug_write


@dataclass
class PipelineResult:
    """Outcome of running process_csv()."""

    invoices: list = field(default_factory=list)
    trimmed_df: Optional[pd.DataFrame] = None
    pending_orders: list = field(default_factory=list)
    cancelled_count: int = 0
    preorder_count: int = 0
    auto_return_count: int = 0
    # Only populated when decisions is None and unresolved returns remain —
    # callers should short-circuit into the review flow in that case.
    return_items: list = field(default_factory=list)
    needs_return_review: bool = False


def process_csv(parser, csv_path: str, decisions: Optional[List[dict]] = None) -> PipelineResult:
    """Run the shared CSV pipeline and return a PipelineResult.

    If decisions is None: unresolved (unknown-status) return items are detected
    via parser.detect_return_items(). If any are found, the result is returned
    immediately with needs_return_review=True and return_items populated — the
    caller should surface this to the user for review instead of parsing
    invoices (matches the old save_mapping() short-circuit behavior).

    If decisions is a list (possibly empty): parser.apply_return_decisions()
    is applied instead of the detect/short-circuit check (matches the old
    apply_return_decisions() behavior, which never called detect_return_items).
    """
    result = PipelineResult()

    df = parser.read_csv(csv_path)
    debug_write('01_raw_loaded', df)

    df, result.cancelled_count = parser.filter_cancelled_invoices(df)

    # Drop pre-order rows for platforms that mark them (TikTok 'Normal or Pre-order')
    df, result.preorder_count = parser.filter_preorders(df)

    # Auto-remove confirmed returns (e.g. สถานะการคืนเงินหรือคืนสินค้า = คำขอได้รับการยอมรับแล้ว).
    # For Shopee, if the returned item is in row1, invoice-level fields are
    # forward-filled before deletion so no customer/address info is lost.
    df, result.auto_return_count = parser.filter_confirmed_returns(df)
    debug_write('02_after_filter', df)

    if decisions is None:
        # Check for any remaining return items with unknown status (still need user review)
        return_items = parser.detect_return_items(df)
        if return_items:
            result.return_items = return_items
            result.needs_return_review = True
            return result
    else:
        # Apply user decisions for any remaining unknown-status returns
        df = parser.apply_return_decisions(df, decisions)

    # Split shipped vs pending (unshipped) orders
    df_shipped, pending_df = parser.split_pending_orders(df)
    result.pending_orders = parser.get_pending_summary(pending_df)

    # Store trimmed df for sales report (shipped only). Always forward-fill —
    # see the DELIBERATE FIX note above.
    trimmed_df = df_shipped.copy()
    trimmed_df = parser._forward_fill_invoice_fields(trimmed_df)
    result.trimmed_df = trimmed_df

    # Parse invoices from shipped-only df
    grouped = parser.group_by_invoice(df_shipped)
    # DEBUG step 3: invoice groups before parsing (one row per group)
    _order_date_col = parser.column_map.get('order_date', '')
    _payment_col = parser.column_map.get('payment_time', '')
    _tax_col = parser.column_map.get('tax_invoice', '')
    _name_col = parser.column_map.get('recipient_name', '')
    debug_write('03_invoice_groups', [
        {
            'group_rank': rank + 1,
            'invoice_number': inv_num,
            'row_count': len(grp),
            'raw_ship_date': str(grp.iloc[0][_order_date_col]) if _order_date_col and _order_date_col in grp.columns else '',
            'raw_payment_date': str(grp.iloc[0][_payment_col]) if _payment_col and _payment_col in grp.columns else '',
            'customer_name': str(grp.iloc[0][_name_col]) if _name_col and _name_col in grp.columns else '',
        }
        for rank, (inv_num, grp) in enumerate(grouped.items())
    ], columns=['group_rank', 'invoice_number', 'row_count', 'raw_ship_date', 'raw_payment_date', 'customer_name'])

    invoices = []
    for invoice_num, invoice_df in grouped.items():
        try:
            invoice = parser.parse_invoice(invoice_df, invoice_num)
            invoices.append(invoice)
        except Exception as e:
            print(f"Warning: Failed to parse invoice {invoice_num}: {e}")
            continue
    invoices.sort(key=lambda inv: inv.order_sort_key or '9999-99-99 99:99:99')
    # DEBUG step 4: final invoice sort order
    debug_write('04_sort_order', [
        {
            'sort_rank': rank + 1,
            'invoice_number': inv.invoice_number,
            'customer_name': inv.customer.name if inv.customer else '',
            'order_date_display': inv.order_date,
            'order_sort_key': inv.order_sort_key,
        }
        for rank, inv in enumerate(invoices)
    ], columns=['sort_rank', 'invoice_number', 'customer_name', 'order_date_display', 'order_sort_key'])

    # Lock 0-based bill order into each Invoice object
    for i, inv in enumerate(invoices):
        inv.order_index = i
    result.invoices = invoices

    # Stamp __bill_order__ onto trimmed df — single source of truth for all downstream ops
    tax_col = parser.column_map.get('tax_invoice') or parser.column_map.get('order_id')
    if tax_col and tax_col in trimmed_df.columns:
        order_map = {inv.invoice_number: inv.order_index for inv in invoices}
        trimmed_df['__bill_order__'] = (
            trimmed_df[tax_col].astype(str).str.strip().map(order_map)
        )

    return result
