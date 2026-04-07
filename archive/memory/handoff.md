# Session Handoff — 2026-02-26

## Status
**v2.5 is the current release.** Both `Batch_Bill_Print_v2.5_mac.zip` and `Batch_Bill_Print_v2.5_windows.zip` are in the project root. Both share the same `src/`. v2.4 mac archived (v2.4 windows was never built).

### v2.5 changes (on top of v2.4)
**Bug fix — Jan orders sorting after Feb orders (root cause: 2-digit year date format not parsed).**

- `src/csv_parser.py` — `_parse_sort_key`: Added `%d/%m/%y %H:%M:%S`, `%d/%m/%y %H:%M`, `%d/%m/%y` formats.
  - Shopee's `เวลาส่งสินค้า` column uses `DD/MM/YY HH:MM` (2-digit year). Previously unrecognised → fell back to raw string → string compare `"02/02/26" < "05/01/26"` (Feb 2 before Jan 5). Now parses to ISO → correct chronological sort.
  - Ship time remains the primary sort key. Payment time is still the fallback for blank ship times (unshipped orders) only.

---

### v2.2 changes (on top of v2.1)
**Single-source bill number — stamp once, read everywhere.**

- `app.py`: Added `_assign_bill_numbers(bill_prefix, bill_start_num)` — the **only** place `bill_number` is computed. Sets `invoice.bill_number` on all Invoice objects AND stamps `current_trimmed_df['__bill_number__']`.
- All generation/preview endpoints call `_assign_bill_numbers` then read pre-set values — no independent re-computation.
- `/sales-report`: calls `_assign_bill_numbers` before `_build_sales_data`.
- `_build_sales_data`: reads `__bill_number__` from DF row directly; fallback to `order_index` formula only if column absent (edge case: sales report before any generation).
- `generate_batch_bills`: removed the `invoice.bill_number = ...` re-computation line; reads pre-stamped value. Removed `bill_prefix` param (now unused).
- `/debug-bills` GET endpoint: open `http://localhost:5003/debug-bills` after generating to inspect order↔bill-number mapping as JSON.

### Data flow (v2.2)
```
/save-mapping or /apply-return-decisions
  → sort invoices → stamp __bill_order__ (int) on DF + order_index on Invoice

Any generation/preview endpoint:
  → _assign_bill_numbers(prefix, start)
       ├─ Invoice.bill_number = "prefix+N"   ← PDF generator reads this
       └─ DF['__bill_number__'] = "prefix+N" ← sales report reads this
```

---

## Bug Report Pending Investigation

**Report:** Order `260212GQR5R54C` (status = `ยกเลิกแล้ว`) still appears in bill printing output when using test file:
`/Users/parin/Library/Mobile Documents/com~apple~CloudDocs/VS_Code/Bill_Print/Test_MKP_Shopee.csv`

**Key finding (already verified this session):**
The backend `filter_cancelled_invoices()` in `src/csv_parser.py` **CORRECTLY removes the cancelled order** when tested directly. Python test confirmed:
- Input: 4 orders, 12 rows
- After filter: 3 orders, 11 rows — `260212GQR5R54C` is gone ✓

So the backend is NOT broken. The issue is likely one of:
1. **Server not restarted** after code changes (Flask must be restarted to pick up fixes)
2. **Old cached PDFs** in `output/bills/` from a previous run — user downloads stale files
3. **save-mapping step skipped** — user may have uploaded CSV but not clicked Save/Validate to trigger invoice re-parsing
4. **Platform not selected** in UI before uploading (falls back to default mapping instead of Shopee preset)

**Next session action:** Ask user to:
1. Stop server (Ctrl+C), restart (`./run.sh`)
2. Re-upload CSV → select Shopee → click Save Mapping
3. Verify the success message says "3 invoices" (not 4)
4. Then generate bills

---

## New Shopee CSV Format Discovered (MKP export)

The real-world `Test_MKP_Shopee.csv` is a **Marketplace (MKP) format** that differs from `shoppee_sample_file.csv`:

| | Sample CSV (old) | Test MKP CSV (real) |
|---|---|---|
| Multi-item orders | Order info only in ROW 1, rows 2+ blank | **ALL rows have complete data** |
| Extra columns | — | `Hot Listing` (col 2), `เหตุผลในการยกเลิกคำสั่งซื้อ` (col 3), `โค้ด Coins Cashback ชำระโดยผู้ขาย` (col 28), `ส่วนลดเครื่องเก่าแลกใหม่` (col 36), `โบนัสส่วนลดเครื่องเก่าแลกใหม่` (col 37), `ค่าจัดส่งสินค้าคืน` (col 43), `โบนัสส่วนลดเครื่องเก่าแลกใหม่จากผู้ขาย` (col 47) |
| Total columns | ~49 | **59** |
| Successful status | `สำเร็จแล้ว` | Also `จัดส่งสำเร็จแล้ว` (different value!) |

**Critical: `จัดส่งสำเร็จแล้ว` is not in any preset** — if platform's "successful" statuses need to be whitelisted anywhere in the code, this new status needs adding. Currently the code only EXCLUDES `ยกเลิกแล้ว` (cancelled), so `จัดส่งสำเร็จแล้ว` passes through fine as a non-cancelled order.

**All key mapping columns ARE present** in the MKP format — platform detection and filtering work correctly with the MKP CSV.

---

## What Was Fixed This Session (v1.7)

### 1. Shopee discount column (`src/platform_presets.py`)
- Changed `shopee_discount` from `'ส่วนลดจาก Shopee'` → `'โค้ดส่วนลดชำระโดยผู้ขาย'`

### 2. Cancelled orders filter bug (`src/csv_parser.py` — `filter_cancelled_invoices`)
- **Bug:** For old Shopee sparse format, rows 2+ had blank order_id. When a multi-item order was cancelled, only row 1 was removed; rows 2+ remained with blank order_id and got forward-filled onto the PREVIOUS order.
- **Fix:** Forward-fill order_id before filtering (no-op for MKP format where every row has order_id).

### 3. Confirmed returns auto-filter (`src/csv_parser.py` — new `filter_confirmed_returns`)
- New method auto-removes rows where `สถานะการคืนเงินหรือคืนสินค้า` = `คำขอได้รับการยอมรับแล้ว`
- **Safe for Shopee row1 edge case:** forward-fills invoice-level fields BEFORE deleting, so customer/address info is preserved in remaining item rows
- Called in both `/save-mapping` and `/apply-return-decisions` in `app.py`

### Files changed
- `src/platform_presets.py`
- `src/csv_parser.py`
- `app.py`
- `Batch_Bill_Print_v1.6_windows/src/platform_presets.py`
- `Batch_Bill_Print_v1.6_windows/src/csv_parser.py`
- `Batch_Bill_Print_v1.6_windows/app.py`

### Distribution
- `Batch_Bill_Print_v1.7_mac.zip` — created and ready in project root
- Windows v1.7 zip NOT yet created (Windows folder updated but not zipped)

---

## Bug Fixed This Session (v1.8 candidate)

### February bills printing before January bills on client machines

**Symptom:** On some client machines (not dev machine), bill 2600001 was being assigned to a February-shipped order like `260131G92DX82T` (shipped 02/02/2026) instead of a January order.

**Root cause:** `groupby(sort=False)` in `group_by_invoice()` is supposed to preserve DataFrame insertion order, but its behaviour can vary across pandas versions and OS environments. The post-parse `current_invoices.sort()` was the only safety net — if anything caused it to produce equal keys or fall back to raw strings, invoice order could be wrong.

**Fix (`src/csv_parser.py` — `group_by_invoice`):**
Sort the DataFrame by the `order_date` column **as a raw string** BEFORE calling `groupby`. Shopee and TikTok store dates as `YYYY-MM-DD HH:MM`, so string comparison = chronological order. No date parsing required, no locale or pandas-version sensitivity.

```python
order_date_col = self.column_map.get('order_date')
if order_date_col and order_date_col in df_filtered.columns:
    df_filtered = df_filtered.sort_values(
        by=order_date_col, kind='stable', na_position='last'
    )
```

The existing `current_invoices.sort()` in `app.py` remains as a safety net.

**Status:** Fixed in `src/csv_parser.py`. Verified correct on dev machine with test6.csv (801 invoices, all Jan before Feb). Awaiting confirmation on client machine.
Both Mac and Windows v2.0 zips include this fix. v1.9 archived.
