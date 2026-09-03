"""Shared route helpers extracted from app.py.

Plain functions (not Flask routes) used by every blueprint: login gating,
per-session state access, parser/company-info factories, and the
bill-number utilities. `config` and `SESSION_STORE` live in sibling
modules (config_store.py / state.py) so every blueprint shares the exact
same objects app.py created.
"""
import os
import re
import uuid
from functools import wraps

import pandas as pd
from flask import session, redirect, url_for

from src.csv_parser import CSVParser
from src.platform_presets import PLATFORM_PRESETS
from src.bill_data import CompanyInfo
from src.debug_util import debug_write

from src.web.config_store import config
from src.web.state import SESSION_STORE

APP_PASSWORD = os.environ.get('APP_PASSWORD', '')


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not APP_PASSWORD:
            return f(*args, **kwargs)
        if not session.get('logged_in'):
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def parse_bill_number(bill_str):
    """Parse a bill number string into (prefix, numeric_part).

    Examples:
        '2600001'    -> ('', 2600001)
        'LZ26000015' -> ('LZ', 26000015)
        'TT26000015' -> ('TT', 26000015)
    """
    bill_str = str(bill_str).strip()
    match = re.match(r'^([A-Za-z]*)(\d+)$', bill_str)
    if match:
        return match.group(1), int(match.group(2))
    # Fallback: treat entire string as-is with no prefix
    try:
        return '', int(bill_str)
    except ValueError:
        return bill_str, 0


def format_bill_number(prefix, number):
    """Re-combine prefix + number into a bill number string."""
    return f"{prefix}{number}"


def _assign_bill_numbers(state, bill_prefix, bill_start_num):
    """Compute bill numbers once and stamp them on Invoice objects and the trimmed DataFrame.

    This is the single place where bill_number is written. All consumers (PDF generator,
    sales report) read the pre-stamped value — zero re-computation downstream.
    """
    for inv in state.invoices:
        inv.bill_number = f"{bill_prefix}{bill_start_num + inv.order_index}"
    if state.trimmed_df is not None and '__bill_order__' in state.trimmed_df.columns:
        state.trimmed_df['__bill_number__'] = state.trimmed_df['__bill_order__'].apply(
            lambda idx: f"{bill_prefix}{bill_start_num + int(idx)}" if pd.notna(idx) else ''
        )
    # DEBUG step 5: final bill ↔ invoice assignment
    debug_write('05_bill_assignment', [
        {
            'bill_number': inv.bill_number,
            'invoice_number': inv.invoice_number,
            'customer_name': inv.customer.name if inv.customer else '',
            'order_date': inv.order_date,
            'order_sort_key': inv.order_sort_key,
            'order_index': inv.order_index,
        }
        for inv in state.invoices
    ], columns=['bill_number', 'invoice_number', 'customer_name', 'order_date', 'order_sort_key', 'order_index'])


def _ensure_sid():
    """Return this browser's session id, creating and cookie-storing one if needed."""
    sid = session.get('sid')
    if not sid:
        sid = uuid.uuid4().hex
        session['sid'] = sid
    return sid


def get_sid():
    """Public alias for _ensure_sid(), for routes that need the raw sid (e.g. to
    namespace upload/output directories)."""
    return _ensure_sid()


def get_state():
    """Return (creating if needed) the SessionState for this browser session."""
    return SESSION_STORE.get(_ensure_sid())


def save_state(state):
    """Persist this browser session's SessionState (in-memory + disk spill)."""
    SESSION_STORE.save(_ensure_sid(), state)


def _get_platform_preset(platform):
    """Get the platform preset for a platform key, or None"""
    if platform:
        return PLATFORM_PRESETS.get(platform)
    return None


def _make_parser(platform, custom_column_map=None):
    """Create a CSVParser for the given platform and optional custom mapping"""
    return CSVParser(
        vat_rate=config['settings']['vat_rate'],
        custom_column_map=custom_column_map,
        platform=_get_platform_preset(platform)
    )


def get_company_info():
    """Get company info from config"""
    c = config['company']
    return CompanyInfo(
        name=c['name'],
        tax_id=c['tax_id'],
        address=c['address'],
        phone=c['phone'],
        branch_code=c.get('branch_code', ''),
        branch_address=c.get('branch_address', '')
    )


def _build_invoice_lookup(invoices):
    """Assemble the per-order lookup dict that build_sales_data() needs from
    session-state Invoice objects. Shared by /sales-report and /sales-report-export."""
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
