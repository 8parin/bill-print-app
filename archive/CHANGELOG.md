# Batch Bill Print — Changelog

---

## v2.3 — 2026-02-26

### Fix: Clear `__pycache__` on install to prevent stale bytecode

**Problem**
When a user extracts a new ZIP over an existing install, Python's compiled `.pyc`
files in `__pycache__/` directories may survive with timestamps that appear newer
than the freshly extracted `.py` files. Python then executes the old bytecode,
meaning fixes pushed in `.py` files (e.g. `_assign_bill_numbers` call sequence in
`src/pdf_generator_reportlab.py`) silently never take effect for the user.

A secondary risk: if the Flask server is still running during extraction, the
in-memory module code also continues running the old logic.

**Changes**
| File | Change |
|---|---|
| `install.sh` | Added `find . -type d -name "__pycache__" -exec rm -rf {} +` and `find . -name "*.pyc" -delete` near the top, before Python checks. Added banner warning user to stop the running server first. |
| `install.bat` | Added `for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"` and `del /s /q "*.pyc"` near the top. Added equivalent server-stop warning banner. |

**Distributions**
- `Batch_Bill_Print_v2.3_mac.zip`
- `Batch_Bill_Print_v2.3_windows.zip`

> No application code changed. Install-script-only fix.

---

## v2.2 — 2026-02-26

- Bill number assignment refactored: `_assign_bill_numbers()` called explicitly in
  `generate_batch_bills()` to guarantee sequential numbering across all invoices.
- CSV parser hardening: resilient column detection for varied platform export formats.
- `config.json` persists column mappings between sessions.

---

## v2.1 — 2026-02-23

- Multi-platform CSV presets (Shopee, Lazada, WooCommerce, generic).
- Real-time progress bar during batch generation.
- Windows installer (`install.bat`, `run.bat`) and desktop shortcut via PowerShell.

---

## v1.2 — 2026-02-13

- Custom bill template support (`templates/bill_template.html`).
- Logo placement and margin controls in UI.

---

## v1.1 — 2026-02-11

- Initial public release.
- Flask webapp with CSV upload, column mapping, PDF generation via ReportLab.
- macOS installer (`install.sh`) and desktop shortcut.
