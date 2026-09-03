"""
CSV file reading and column/mapping validation.

This module owns turning a file on disk into a cleaned DataFrame
(read_csv/detect_columns) and comparing a DataFrame's columns against a
ParseContext's column_map (validate_csv, validate_csv_format,
get_column_differences). It does not filter rows by business status
(order_filters.py), build Invoice objects (assembly.py), or clean
individual cell values (normalize.py) — it only deals in whole
dataframes and column names.
"""
from typing import List, Tuple

import pandas as pd


def read_csv(context, file_path: str) -> Tuple[pd.DataFrame, "str | None"]:
    """Read CSV file with proper encoding. dtype=str prevents large integers
    (e.g. order IDs) from being converted to float and displaying as 5.82E+17 in Excel.

    Returns (df, first_column_warning) — first_column_warning is None unless the
    first column doesn't match the expected order_id column (Shopee-only signal
    used to detect corrupted/mis-exported CSVs).
    """
    try:
        df = pd.read_csv(file_path, encoding='utf-8', dtype=str)
    except UnicodeDecodeError:
        df = pd.read_csv(file_path, encoding='tis-620', dtype=str)

    # Shopee exports can end with trailing rows that are entirely blank
    # (all-comma lines). If left in, forward-fill logic elsewhere would
    # attribute them to the last real order, producing a bogus "nan" /
    # qty 0 line item on that order's bill. Drop rows that are blank
    # (NaN or whitespace-only) across every column, without mutating
    # real blank-string cells elsewhere (those are relied on by later
    # `.replace('', pd.NA)` calls).
    blank_mask = df.replace(r'^\s*$', pd.NA, regex=True).isna().all(axis=1)
    if blank_mask.any():
        df = df[~blank_mask]
    df = df.reset_index(drop=True)

    # Strip whitespace and BOM from column names
    df.columns = [col.strip().lstrip('﻿') for col in df.columns]

    # Platform-specific: skip metadata/description rows (e.g. TikTok row 2).
    # TikTok exports inconsistently include a description row right after the
    # header — newer exports omit it. Use multiple signals so we don't drop a
    # real order row by mistake. A row is treated as a description row if ANY
    # signal flags it:
    #   - order_id value is not all digits
    #   - quantity value is not a positive integer
    #   - order_type value (if column exists) is not Normal/Pre-order
    if context.platform and context.platform.skip_rows:
        order_col = context.column_map.get('order_id', '')
        qty_col = context.column_map.get('quantity', '')
        type_col = context.column_map.get('order_type', '')
        rows_to_skip = []
        for i in context.platform.skip_rows:
            if i >= len(df):
                continue
            if i == 0:
                looks_like_description = False
                if order_col and order_col in df.columns:
                    val = str(df.at[i, order_col]).strip()
                    if not val.isdigit():
                        looks_like_description = True
                if qty_col and qty_col in df.columns:
                    qval = str(df.at[i, qty_col]).strip()
                    if not (qval.isdigit() and int(qval) > 0):
                        looks_like_description = True
                if type_col and type_col in df.columns:
                    tval = str(df.at[i, type_col]).strip()
                    if tval and tval not in ('Normal', 'Pre-order'):
                        looks_like_description = True
                if not looks_like_description:
                    continue  # real data row, don't skip
            rows_to_skip.append(i)
        if rows_to_skip:
            df = df.drop(index=rows_to_skip).reset_index(drop=True)

    # First-column validation (only for Shopee)
    first_column_warning = None
    if context.platform and context.platform.name == 'shopee':
        first_col = df.columns[0] if len(df.columns) > 0 else ''
        expected_first = context.column_map.get('order_id', '')
        if first_col != expected_first:
            first_column_warning = (
                f"First column is '{first_col}' instead of '{expected_first}'. "
                f"The CSV file may be corrupted — please re-export from Shopee."
            )
    elif not context.platform:
        # Legacy behavior when no platform specified
        first_col = df.columns[0] if len(df.columns) > 0 else ''
        if first_col != 'หมายเลขคำสั่งซื้อ':
            first_column_warning = (
                f"First column is '{first_col}' instead of 'หมายเลขคำสั่งซื้อ'. "
                f"The CSV file may be corrupted — please re-export."
            )

    return df, first_column_warning


def detect_columns(context, file_path: str) -> List[str]:
    """Detect all columns in the CSV file"""
    df, _ = read_csv(context, file_path)
    return list(df.columns)


def validate_csv(context, df: pd.DataFrame) -> Tuple[bool, List[str]]:
    """Validate CSV has required columns"""
    errors = []
    required_cols = [
        context.column_map['order_id'],
        context.column_map['product_name'],
        context.column_map['recipient_name']
    ]

    for col in required_cols:
        if col not in df.columns:
            errors.append(f"Missing required column: {col}")

    if errors:
        return False, errors
    return True, []


def validate_csv_format(context, df: pd.DataFrame) -> Tuple[bool, dict]:
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
    expected_cols = set(context.column_map.values())

    # Check for missing required columns
    required_fields = ['order_id', 'product_name', 'recipient_name', 'address', 'phone']
    for field in required_fields:
        col_name = context.column_map.get(field, '')
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

        platform_name = context.platform.display_name if context.platform else 'the platform'
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


def get_column_differences(context, detected_columns: List[str]) -> dict:
    """Compare detected columns with expected mapping"""
    expected = set(context.column_map.values())
    detected = set(detected_columns)

    return {
        'expected_columns': list(expected),
        'detected_columns': detected_columns,
        'missing': list(expected - detected),
        'extra': list(detected - expected),
        'matched': list(expected & detected)
    }
