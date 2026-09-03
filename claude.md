# Bill Print App — Project Reference

**Deployment**: Render (web service) — https://bill-print-app.onrender.com  
**Stack**: Python 3.11 / Flask / ReportLab / Gunicorn  
**Last Updated**: 2026-04-07

---

## Project Structure

```
Bill_Print/
├── app.py                    # Thin entry point: app factory-ish setup + blueprint registration
├── render.yaml               # Render deployment config
├── requirements.txt          # Python dependencies (runtime)
├── requirements-dev.txt      # + pytest, for local/dev use
├── .python-version           # Pins Python 3.11 for Render
├── .env.example              # Required environment variables
├── config.json               # App config (column mappings etc.)
│
├── src/
│   ├── csv_parser.py              # CSVParser: thin backward-compat facade over src/parsing/
│   ├── parsing/                    # CSV parsing internals (Phase 5 split of csv_parser.py)
│   │   ├── context.py              # ParseContext (platform, column_map, vat_rate) + mapping validation
│   │   ├── csv_io.py               # read_csv, detect_columns, validate_csv(_format), column diffs
│   │   ├── normalize.py            # pure cleaning: clean_numeric, date parse/format, address text
│   │   ├── order_filters.py        # cancelled/preorder/return filtering, forward-fill, pending split
│   │   └── assembly.py             # group_by_invoice, parse_invoice, parse_csv_to_invoices
│   ├── bill_data.py               # Dataclasses: CompanyInfo, Customer, LineItem, Invoice
│   ├── pdf_generator_reportlab.py # Active PDF generator (ReportLab)
│   ├── platform_presets.py        # Shopee / Lazada / TikTok column maps & quirks
│   ├── database.py                # Postgres persistence (company profiles)
│   ├── pipeline.py                # Shared CSV -> invoices processing (process_csv)
│   ├── session_state.py           # SessionState / SessionStore (per-browser state)
│   ├── sales_report.py            # Sales report PDF/CSV/XLSX builders
│   ├── fonts.py                   # Thai font loading for ReportLab
│   ├── debug_util.py              # Optional debug CSV dumps (DEBUG_DIR)
│   │
│   └── web/                       # Flask web layer (Phase 4)
│       ├── config_store.py        # Shared `config` dict, loaded once from config.json
│       ├── state.py               # Shared SESSION_STORE singleton
│       ├── helpers.py             # login_required, get_state/save_state/get_sid,
│       │                          # _make_parser, get_company_info, bill-number helpers
│       └── routes/                # One blueprint per feature area
│           ├── auth.py            # login, logout, index ('/')
│           ├── uploads.py         # upload, set-platform, save-mapping,
│           │                      # apply-return-decisions, get-field-definitions
│           ├── bills.py           # preview*, generate*, download*, debug-bills,
│           │                      # stats, version
│           ├── profiles.py        # save-company, api/company-profiles*
│           └── reports.py         # sales-report(-export), sort-csv
│
├── templates/                 # Flask HTML templates
│   ├── index.html
│   ├── login.html
│   └── bill_template.html
│
├── static/                    # CSS / JS / images
├── tests/                     # pytest suite
│   ├── fixtures/               # Sample CSVs (shopee_sample.csv, lazada_sample.csv, tiktok_sample.csv)
│   ├── test_bill_data.py
│   ├── test_csv_parser.py         # golden regression values — CSVParser facade
│   ├── test_normalize.py          # unit tests for src/parsing/normalize.py
│   └── test_app.py
├── uploads/                    # Uploaded CSVs (temp, gitignored)
└── output/                     # Generated PDFs (temp, /tmp on Render, gitignored)
```

## Code Navigation — "to change X, edit Y"

| Task | File(s) |
|---|---|
| Bill PDF layout / fonts / paper size | `src/pdf_generator_reportlab.py`, `src/fonts.py`, `fonts/` |
| Bill preview HTML | `templates/bill_template.html` |
| CSV parsing, date/number cleaning, return & cancel filtering | `src/parsing/` (`csv_io.py`, `normalize.py`, `order_filters.py`, `assembly.py`); `src/csv_parser.py` is a backward-compat facade — new code should import `src/parsing/` directly |
| Column-map resolution (custom > platform preset > default) & required-field validation | `src/parsing/context.py` (`ParseContext`) |
| Order of processing steps (filter → group → parse → sort) | `src/pipeline.py` (`process_csv`) |
| Add/adjust a marketplace platform (columns, quirks, report columns) | `src/platform_presets.py` |
| VAT math, invoice/line-item fields | `src/bill_data.py` |
| Sales report PDF/CSV/XLSX content | `src/sales_report.py` |
| A specific URL route | `src/web/routes/` — auth.py (`/`, login), uploads.py (upload/mapping), bills.py (preview/generate/download/version), profiles.py (company profiles), reports.py (sales report, sort-csv) |
| Per-browser session state | `src/session_state.py` + `src/web/state.py` |
| Shared route helpers (auth decorator, bill numbering, state access) | `src/web/helpers.py` |
| App config dict (config.json) | `src/web/config_store.py` |
| Company profile DB persistence | `src/database.py` |
| Frontend behavior | `static/js/app.js`, `templates/index.html` |
| App startup / blueprint wiring / env guards | `app.py` (keep `gunicorn app:app` working) |

**Verify any change**: `.venv/bin/python -m pytest tests/ -q` (bare `python3` lacks deps). Golden regression values live in `tests/test_csv_parser.py` — if they fail, you changed billing math.
**Check what's deployed**: https://bill-print-app.onrender.com/version returns the live commit.
**Gotcha**: blueprints resolve `_make_parser` and DB functions dynamically via `import app` — don't remove the re-exports at the top of `app.py`.

---

## Deployment (Render)

### Render Config (`render.yaml`)

```yaml
services:
  - type: web
    name: bill-print-app
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app
    envVars:
      - key: DATABASE_URL
        sync: false          # Set manually in Render dashboard
      - key: FLASK_ENV
        value: production
      - key: OUTPUT_DIR
        value: /tmp/output/bills
```

Python version is controlled by `.python-version` (currently `3.11.0`).  
Do NOT rely on `PYTHON_VERSION` env var — Render ignores it for version selection.

### Required Environment Variables (set in Render dashboard)

| Variable | Description |
|---|---|
| `DATABASE_URL` | Neon PostgreSQL connection string |
| `FLASK_ENV` | Set to `production` |
| `OUTPUT_DIR` | Set to `/tmp/output/bills` |

### First Deploy Checklist

1. Push to GitHub (main branch)
2. Render auto-deploys via `render.yaml` blueprint
3. Set `DATABASE_URL` in Render dashboard → Environment
4. After deploy, init DB via Render Shell:
   ```bash
   python -c "from src.database import init_database; init_database()"
   ```
5. Test at https://bill-print-app.onrender.com

---

## Debugging Build Failures via Render MCP

Render's MCP server (`https://mcp.render.com/mcp`) uses **Streamable HTTP transport**.  
Claude Code doesn't natively support adding this MCP server via settings, so use this manual method:

### Step 1 — Initialize session

```bash
SESSION=$(curl -si -X POST "https://mcp.render.com/mcp" \
  -H "Authorization: Bearer <RENDER_API_KEY>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"claude-code","version":"1.0"}}}' \
  | grep "mcp-session-id" | awk '{print $2}' | tr -d '\r')
echo "Session: $SESSION"
```

### Step 2 — Select workspace (required once per session)

```bash
curl -s -X POST "https://mcp.render.com/mcp" \
  -H "Authorization: Bearer <RENDER_API_KEY>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_workspaces","arguments":{}}}'
```

### Step 3 — Fetch build logs

```bash
curl -s -X POST "https://mcp.render.com/mcp" \
  -H "Authorization: Bearer <RENDER_API_KEY>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SESSION" \
  -d '{
    "jsonrpc": "2.0", "id": 3,
    "method": "tools/call",
    "params": {
      "name": "list_logs",
      "arguments": {
        "resource": ["<SERVICE_ID>"],
        "type": ["build"],
        "startTime": "<RFC3339_START>",
        "endTime": "<RFC3339_END>",
        "direction": "forward",
        "limit": 100
      }
    }
  }' | python3 -c "
import sys, json, re
data = json.load(sys.stdin)
ansi = re.compile(r'\x1B(?:[@-Z\\\\-_]|\[[0-?]*[ -/]*[@-~])')
for e in data['result']['content']:
    inner = json.loads(e['text'])
    for log in inner.get('logs', []):
        print(ansi.sub('', log['message']))
"
```

To find deploy timestamps, first call `list_deploys`:

```bash
curl -s -X POST "https://mcp.render.com/mcp" \
  -H "Authorization: Bearer <RENDER_API_KEY>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"list_deploys","arguments":{"serviceId":"<SERVICE_ID>","limit":5}}}'
```

### Render Resource IDs (this project)

| Resource | ID |
|---|---|
| Service | `srv-d7a9g7udqaus73arsorg` |
| Owner | `tea-d7a7n395pdvs73c2cftg` |

The Render API key is stored in the Cline MCP settings at:  
`~/Library/Application Support/Antigravity/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`
and
.env RENDER_API_KEY = 

### Available MCP Tools

`list_logs`, `list_deploys`, `get_deploy`, `get_service`, `list_services`,  
`get_metrics`, `update_environment_variables`, `update_web_service`, and more.  
Run `tools/list` (id=2) after initializing to see the full list.

---

## Known Issues & Fixes

### pandas build failure on Python 3.14 (April 2026)

Render defaulted to Python 3.14.3 which broke `pandas==2.1.4` compilation  
(`_PyLong_AsByteArray` API changed in CPython 3.14).

**Fix**: `.python-version` file pinning `3.11.0` — already applied.

---

## Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py          # runs on http://localhost:5003
```

---

## Supported CSV Formats

- Shopee, Lazada, TikTok Shop, WooCommerce, generic CSV
- Sample files in `tests/fixtures/` folder
- Minimum required columns: Invoice/Order Number, Customer Name, Item Name, Quantity, Price, Date
