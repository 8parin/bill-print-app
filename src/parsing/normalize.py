"""
Pure normalization helpers: numeric cleaning, date parsing/formatting,
address/text sanitization. Nothing here reads a file, filters a dataframe,
or knows about invoices/line items — functions take only the plain values
(or a ParseContext, when platform date-offset/address-field info is
needed) they operate on and return a cleaned value. Row/dataframe-level
orchestration belongs in csv_io.py, order_filters.py or assembly.py.
"""
from datetime import datetime, timedelta

import pandas as pd


def clean_numeric(value) -> float:
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


def parse_sort_key(raw_date: str, context=None) -> str:
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
            platform = getattr(context, 'platform', None) if context is not None else None
            if platform and getattr(platform, 'date_offset_days', 0):
                parsed += timedelta(days=platform.date_offset_days)
            return parsed.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
    return date_str  # fallback: use raw string (works for ISO-like formats)


def format_order_date(raw_date: str, context=None) -> str:
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
    platform = getattr(context, 'platform', None) if context is not None else None
    offset = 0
    if platform and hasattr(platform, 'date_offset_days'):
        offset = platform.date_offset_days
    if offset:
        parsed_date += timedelta(days=offset)

    return parsed_date.strftime('%d/%m/%Y')


def clean_address(text: str) -> str:
    """Remove characters that render as boxes in PDF fonts (zero-width spaces,
    non-breaking spaces, embedded newlines from e-commerce exports)."""
    text = text.replace('​', '')   # zero-width space
    text = text.replace(' ', ' ')  # non-breaking space → regular space
    text = text.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
    return ' '.join(text.split())       # collapse multiple spaces


def assemble_address(row, context) -> str:
    """Assemble address from one or more CSV columns.

    For Shopee: single 'address' column.
    For Lazada: shippingAddress + shippingAddress2-5 + city + postcode.
    For TikTok: Detail Address + District + Province + Zipcode.
    """
    platform = context.platform
    column_map = context.column_map
    if platform and len(platform.address_fields) > 1:
        parts = []
        for col_name in platform.address_fields:
            if col_name in row.index:
                val = str(row[col_name]).strip() if pd.notna(row[col_name]) else ''
                if val and val != 'nan':
                    parts.append(val)
        return clean_address(', '.join(parts)) if parts else ''
    else:
        addr_col = column_map.get('address', '')
        if addr_col and addr_col in row.index:
            return clean_address(str(row[addr_col]))
        return ''
