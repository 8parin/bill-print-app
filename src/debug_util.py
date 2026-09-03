"""Debug CSV dump helper, shared by app.py and src/pipeline.py.

No-op unless BILL_DEBUG=1/true — avoid dumping customer data to disk on
every request by default.
"""
import os

import pandas as pd

DEBUG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'debug')


def debug_write(step: str, df_or_rows, columns=None):
    """Write an intermediate debug CSV to the debug/ folder.

    step       – filename prefix, e.g. '01_raw_loaded'
    df_or_rows – a DataFrame OR a list-of-dicts
    columns    – column order override (optional)
    """
    if os.environ.get('BILL_DEBUG', '').strip().lower() not in ('1', 'true'):
        return
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        path = os.path.join(DEBUG_DIR, f"{step}.csv")
        if isinstance(df_or_rows, pd.DataFrame):
            df_or_rows.to_csv(path, index=False, encoding='utf-8-sig')
        else:
            import csv as _csv
            if not df_or_rows:
                return
            cols = columns or list(df_or_rows[0].keys())
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = _csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
                w.writeheader()
                w.writerows(df_or_rows)
        print(f"[DEBUG] wrote {path}")
    except Exception as exc:
        print(f"[DEBUG] could not write {step}: {exc}")
