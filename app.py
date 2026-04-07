"""
Bill Print Flask Application
"""
import os
import json
from io import BytesIO
from flask import Flask, render_template, request, jsonify, send_file, url_for, make_response
from werkzeug.utils import secure_filename
import re
import zipfile
import pandas as pd
from src.csv_parser import CSVParser
from src.platform_presets import PLATFORM_PRESETS, detect_platform
from src.pdf_generator_reportlab import PDFGeneratorReportLab as PDFGenerator
from src.bill_data import CompanyInfo

app = Flask(__name__)


DEBUG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'debug')
os.makedirs(DEBUG_DIR, exist_ok=True)


def _debug_write(step: str, df_or_rows, columns=None):
    """Write an intermediate debug CSV to the debug/ folder.

    step     – filename prefix, e.g. '01_raw_loaded'
    df_or_rows – a DataFrame OR a list-of-dicts
    columns  – column order override (optional)
    """
    try:
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


def _assign_bill_numbers(bill_prefix, bill_start_num):
    """Compute bill numbers once and stamp them on Invoice objects and the trimmed DataFrame.

    This is the single place where bill_number is written. All consumers (PDF generator,
    sales report) read the pre-stamped value — zero re-computation downstream.
    """
    global current_trimmed_df
    for inv in current_invoices:
        inv.bill_number = f"{bill_prefix}{bill_start_num + inv.order_index}"
    if current_trimmed_df is not None and '__bill_order__' in current_trimmed_df.columns:
        current_trimmed_df['__bill_number__'] = current_trimmed_df['__bill_order__'].apply(
            lambda idx: f"{bill_prefix}{bill_start_num + int(idx)}" if pd.notna(idx) else ''
        )
    # DEBUG step 5: final bill ↔ invoice assignment
    _debug_write('05_bill_assignment', [
        {
            'bill_number': inv.bill_number,
            'invoice_number': inv.invoice_number,
            'customer_name': inv.customer.name if inv.customer else '',
            'order_date': inv.order_date,
            'order_sort_key': inv.order_sort_key,
            'order_index': inv.order_index,
        }
        for inv in current_invoices
    ], columns=['bill_number', 'invoice_number', 'customer_name', 'order_date', 'order_sort_key', 'order_index'])


# Load configuration
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

# Configuration - use absolute paths to avoid issues with send_file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, config['settings']['upload_folder'].lstrip('./'))
app.config['OUTPUT_FOLDER'] = os.path.join(BASE_DIR, config['settings']['output_folder'].lstrip('./'))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Ensure directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Global state
current_invoices = []
current_csv_path = None
current_trimmed_df = None  # Trimmed DataFrame (no cancelled/returned orders) for sales report
current_platform = None  # Platform key: 'shopee', 'lazada', 'tiktok', or None
current_pending_orders = []  # Unshipped order summaries (shown on summary page, excluded from bills)


def _get_platform_preset():
    """Get the current platform preset, or None"""
    if current_platform:
        return PLATFORM_PRESETS.get(current_platform)
    return None


def _make_parser(custom_column_map=None):
    """Create a CSVParser with current platform and optional custom mapping"""
    return CSVParser(
        vat_rate=config['settings']['vat_rate'],
        custom_column_map=custom_column_map,
        platform=_get_platform_preset()
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


@app.route('/')
def index():
    """Main page"""
    return render_template('index.html', company=config['company'])


@app.route('/upload', methods=['POST'])
def upload_csv():
    """Handle CSV upload"""
    global current_invoices, current_csv_path, current_platform

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'File must be CSV'}), 400

    try:
        # Save file
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        current_csv_path = filepath

        # Get platform from form data (user's dropdown selection)
        selected_platform = request.form.get('platform', '').strip() or None
        current_platform = selected_platform

        # Create parser with selected platform preset
        preset = _get_platform_preset()
        if preset:
            parser = CSVParser(
                vat_rate=config['settings']['vat_rate'],
                platform=preset
            )
        else:
            parser = CSVParser(
                vat_rate=config['settings']['vat_rate'],
                custom_column_map=config.get('column_mapping')
            )

        detected_columns = parser.detect_columns(filepath)

        # Auto-detect platform from headers (for informational purposes)
        auto_detected = detect_platform(detected_columns)

        # Validate format
        df = parser.read_csv(filepath)
        format_valid, validation_result = parser.validate_csv_format(df)

        # Get column differences for detailed reporting
        column_diff = parser.get_column_differences(detected_columns)

        response_data = {
            'success': True,
            'filename': filename,
            'columns': detected_columns,
            'message': f'CSV uploaded successfully. {len(detected_columns)} columns detected.',
            'format_valid': format_valid,
            'validation': validation_result,
            'column_diff': column_diff,
            'selected_platform': current_platform,
            'auto_detected_platform': auto_detected,
        }

        # Warn if auto-detected platform differs from user selection
        if auto_detected and selected_platform and auto_detected != selected_platform:
            auto_name = PLATFORM_PRESETS[auto_detected].display_name
            response_data['platform_mismatch'] = (
                f'Auto-detected {auto_name}, but you selected '
                f'{PLATFORM_PRESETS[selected_platform].display_name}. '
                f'If columns don\'t match, try changing the platform.'
            )

        if not format_valid:
            response_data['warning'] = True
            response_data['message'] = 'CSV uploaded, but format has changed. Please verify column mapping.'

        if parser.first_column_warning:
            response_data['warning'] = True
            response_data['first_column_error'] = parser.first_column_warning
            response_data['message'] = parser.first_column_warning

        return jsonify(response_data)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/save-company', methods=['POST'])
def save_company():
    """Save company info to config"""
    try:
        data = request.get_json()
        config['company']['name'] = data.get('name', config['company']['name'])
        config['company']['tax_id'] = data.get('tax_id', config['company']['tax_id'])
        config['company']['address'] = data.get('address', config['company']['address'])
        config['company']['phone'] = data.get('phone', config['company']['phone'])

        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        return jsonify({'success': True, 'message': 'Company info saved.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/get-field-definitions')
def get_field_definitions():
    """Get field definitions for mapping UI"""
    parser = _make_parser()
    return jsonify({
        'fields': parser.get_field_definitions(),
        'required_fields': parser.REQUIRED_FIELDS,
        'current_mapping': parser.column_map,
        'platform': current_platform
    })


@app.route('/set-platform', methods=['POST'])
def set_platform():
    """Set the active platform (called when user changes dropdown)"""
    global current_platform
    data = request.get_json() or {}
    current_platform = data.get('platform') or None
    preset = _get_platform_preset()
    return jsonify({
        'success': True,
        'platform': current_platform,
        'platform_name': preset.display_name if preset else 'Unknown'
    })


@app.route('/save-mapping', methods=['POST'])
def save_mapping():
    """Save custom column mapping"""
    global current_invoices, current_csv_path, current_trimmed_df, current_pending_orders
    
    try:
        mapping = request.json.get('mapping', {})
        
        # Validate mapping
        parser = _make_parser()
        valid, errors = parser.validate_mapping(mapping)

        if not valid:
            return jsonify({'error': 'Invalid mapping', 'details': errors}), 400

        # Save to config
        config['column_mapping'] = mapping
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        # Parse CSV with new mapping
        csv_path = current_csv_path
        if not csv_path:
            upload_dir = app.config['UPLOAD_FOLDER']
            csv_files = [f for f in os.listdir(upload_dir) if f.endswith('.csv')]
            if csv_files:
                csv_files.sort(key=lambda f: os.path.getmtime(os.path.join(upload_dir, f)), reverse=True)
                csv_path = os.path.join(upload_dir, csv_files[0])
                current_csv_path = csv_path

        if csv_path:
            parser_with_mapping = _make_parser(custom_column_map=mapping)

            # Read and filter cancelled orders first
            df = parser_with_mapping.read_csv(csv_path)
            # DEBUG step 1: raw CSV as loaded
            _debug_write('01_raw_loaded', df)

            df, cancelled_count = parser_with_mapping.filter_cancelled_invoices(df)

            # Auto-remove confirmed returns (e.g. สถานะการคืนเงินหรือคืนสินค้า = คำขอได้รับการยอมรับแล้ว).
            # For Shopee, if the returned item is in row1, invoice-level fields are
            # forward-filled before deletion so no customer/address info is lost.
            df, auto_return_count = parser_with_mapping.filter_confirmed_returns(df)
            # DEBUG step 2: after cancellation + return filtering
            _debug_write('02_after_filter', df)

            # Check for any remaining return items with unknown status (still need user review)
            return_items = parser_with_mapping.detect_return_items(df)

            if return_items:
                msg = f'Mapping saved! Found return/refund items that need review.'
                parts = []
                if cancelled_count > 0:
                    parts.append(f'{cancelled_count} cancelled invoice(s) filtered out')
                if auto_return_count > 0:
                    parts.append(f'{auto_return_count} confirmed returned item(s) auto-removed')
                if parts:
                    msg += f' ({", ".join(parts)})'

                return jsonify({
                    'success': True,
                    'needs_return_review': True,
                    'return_items': return_items,
                    'cancelled_count': cancelled_count,
                    'auto_return_count': auto_return_count,
                    'message': msg
                })
            else:
                # No remaining returns to review — parse invoices directly
                # Split shipped vs pending (unshipped) orders
                df_shipped, pending_df = parser_with_mapping.split_pending_orders(df)
                current_pending_orders = parser_with_mapping.get_pending_summary(pending_df)

                # Store trimmed df for sales report (shipped only, forward-fill if needed)
                current_trimmed_df = df_shipped.copy()
                current_trimmed_df = parser_with_mapping._forward_fill_invoice_fields(current_trimmed_df)

                # Parse invoices from shipped-only df
                grouped = parser_with_mapping.group_by_invoice(df_shipped)
                # DEBUG step 3: invoice groups before parsing (one row per group)
                _order_date_col = parser_with_mapping.column_map.get('order_date', '')
                _payment_col = parser_with_mapping.column_map.get('payment_time', '')
                _tax_col = parser_with_mapping.column_map.get('tax_invoice', '')
                _name_col = parser_with_mapping.column_map.get('recipient_name', '')
                _debug_write('03_invoice_groups', [
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

                current_invoices = []
                for invoice_num, invoice_df in grouped.items():
                    try:
                        invoice = parser_with_mapping.parse_invoice(invoice_df, invoice_num)
                        current_invoices.append(invoice)
                    except Exception as e:
                        print(f"Warning: Failed to parse invoice {invoice_num}: {e}")
                        continue
                current_invoices.sort(key=lambda inv: inv.order_sort_key or '9999-99-99 99:99:99')
                # DEBUG step 4: final invoice sort order
                _debug_write('04_sort_order', [
                    {
                        'sort_rank': rank + 1,
                        'invoice_number': inv.invoice_number,
                        'customer_name': inv.customer.name if inv.customer else '',
                        'order_date_display': inv.order_date,
                        'order_sort_key': inv.order_sort_key,
                    }
                    for rank, inv in enumerate(current_invoices)
                ], columns=['sort_rank', 'invoice_number', 'customer_name', 'order_date_display', 'order_sort_key'])

                # Lock 0-based bill order into each Invoice object
                for _i, _inv in enumerate(current_invoices):
                    _inv.order_index = _i
                # Stamp __bill_order__ onto trimmed df — single source of truth for all downstream ops
                _tc = parser_with_mapping.column_map.get('tax_invoice') or parser_with_mapping.column_map.get('order_id')
                if _tc and _tc in current_trimmed_df.columns:
                    _order_map = {inv.invoice_number: inv.order_index for inv in current_invoices}
                    current_trimmed_df['__bill_order__'] = (
                        current_trimmed_df[_tc].astype(str).str.strip().map(_order_map)
                    )

                msg = f'Mapping saved! Found {len(current_invoices)} invoices.'
                parts = []
                if cancelled_count > 0:
                    parts.append(f'{cancelled_count} cancelled invoice(s) filtered out')
                if auto_return_count > 0:
                    parts.append(f'{auto_return_count} confirmed returned item(s) auto-removed')
                if parts:
                    msg += f' ({", ".join(parts)})'

                return jsonify({
                    'success': True,
                    'invoice_count': len(current_invoices),
                    'cancelled_count': cancelled_count,
                    'auto_return_count': auto_return_count,
                    'message': msg
                })
        else:
            return jsonify({
                'success': True,
                'message': 'Mapping saved to config. Please upload a CSV file first.'
            })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/apply-return-decisions', methods=['POST'])
def apply_return_decisions():
    """Apply user decisions about returned items, then parse invoices"""
    global current_invoices, current_csv_path, current_trimmed_df, current_pending_orders

    try:
        data = request.get_json() or {}
        decisions = data.get('decisions', [])

        csv_path = current_csv_path
        if not csv_path:
            return jsonify({'error': 'No CSV file loaded. Please upload a CSV first.'}), 400

        # When a platform preset is active, use it directly (ignore saved custom mapping)
        if current_platform:
            parser = _make_parser()
        else:
            mapping = config.get('column_mapping', CSVParser.COLUMN_MAP)
            parser = _make_parser(custom_column_map=mapping)

        # Read CSV and filter cancelled orders
        df = parser.read_csv(csv_path)
        df, cancelled_count = parser.filter_cancelled_invoices(df)

        # Auto-remove confirmed returns (same step as in save_mapping, so row indices match)
        df, auto_return_count = parser.filter_confirmed_returns(df)

        # Apply user decisions for any remaining unknown-status returns
        df = parser.apply_return_decisions(df, decisions)

        # Split shipped vs pending (unshipped) orders — only affects platforms like TikTok
        # where primary date column (Shipped Time) can be NaN
        df, pending_df = parser.split_pending_orders(df)
        current_pending_orders = parser.get_pending_summary(pending_df)

        # Store trimmed df for sales report (shipped orders only, original CSV order preserved)
        current_trimmed_df = df.copy()

        # Count how many items were removed
        removed_products = sum(1 for d in decisions if d.get('action') == 'remove_product')
        removed_bills = sum(1 for d in decisions if d.get('action') == 'remove_bill')

        # Now group and parse invoices from the filtered (shipped-only) DataFrame
        grouped = parser.group_by_invoice(df)
        current_invoices = []
        for invoice_num, invoice_df in grouped.items():
            try:
                invoice = parser.parse_invoice(invoice_df, invoice_num)
                current_invoices.append(invoice)
            except Exception as e:
                print(f"Warning: Failed to parse invoice {invoice_num}: {e}")
                continue

        # Sort invoices by parsed datetime (time trimmed only at display time in format_order_date)
        # This ensures same-day orders are ordered correctly by time
        current_invoices.sort(key=lambda inv: inv.order_sort_key or '9999-99-99 99:99:99')

        # Lock 0-based bill order into each Invoice object
        for _i, _inv in enumerate(current_invoices):
            _inv.order_index = _i
        # Stamp __bill_order__ onto trimmed df — single source of truth for all downstream ops
        _tc = parser.column_map.get('tax_invoice') or parser.column_map.get('order_id')
        if _tc and _tc in current_trimmed_df.columns:
            _order_map = {inv.invoice_number: inv.order_index for inv in current_invoices}
            current_trimmed_df['__bill_order__'] = (
                current_trimmed_df[_tc].astype(str).str.strip().map(_order_map)
            )

        msg = f'Found {len(current_invoices)} invoices.'
        parts = []
        if cancelled_count > 0:
            parts.append(f'{cancelled_count} cancelled')
        if auto_return_count > 0:
            parts.append(f'{auto_return_count} confirmed returned item(s) auto-removed')
        if removed_products > 0:
            parts.append(f'{removed_products} returned product(s) removed')
        if removed_bills > 0:
            parts.append(f'{removed_bills} bill(s) cancelled due to returns')
        if current_pending_orders:
            parts.append(f'{len(current_pending_orders)} pending (not yet shipped)')
        if parts:
            msg += f' ({", ".join(parts)})'

        return jsonify({
            'success': True,
            'invoice_count': len(current_invoices),
            'pending_count': len(current_pending_orders),
            'message': msg
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/preview')
def preview_bill():
    """Preview first bill as HTML"""
    global current_invoices

    if not current_invoices:
        return jsonify({'error': 'No invoices loaded'}), 400

    try:
        # Get first invoice
        invoice = current_invoices[0]
        starting_bill_str = request.args.get('starting_bill_number', '2600001')
        _bill_prefix, _bill_start = parse_bill_number(starting_bill_str)
        _assign_bill_numbers(_bill_prefix, _bill_start)
        company = get_company_info()

        # Return rendered template
        return render_template('bill_template.html', invoice=invoice, company=company)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/preview-by-order', methods=['POST'])
def preview_by_order():
    """Preview specific bill by order number"""
    global current_invoices
    
    if not current_invoices:
        return jsonify({'error': 'No invoices loaded'}), 400
    
    try:
        order_number = request.json.get('order_number', '').strip()
        
        if not order_number:
            return jsonify({'error': 'Order number is required'}), 400
        
        # Find invoice with matching order number OR tax invoice number
        matching_invoice = None
        for invoice in current_invoices:
            if (str(invoice.order_id) == str(order_number) or 
                str(invoice.invoice_number) == str(order_number)):
                matching_invoice = invoice
                break
        
        if not matching_invoice:
            return jsonify({'error': f'Order/Invoice number {order_number} not found'}), 404

        starting_bill_str = str(request.json.get('starting_bill_number', '2600001'))
        _bill_prefix, _bill_start = parse_bill_number(starting_bill_str)
        _assign_bill_numbers(_bill_prefix, _bill_start)

        company = get_company_info()
        html = render_template('bill_template.html', invoice=matching_invoice, company=company)
        
        return jsonify({
            'success': True,
            'html': html,
            'invoice_number': matching_invoice.invoice_number,
            'order_id': matching_invoice.order_id
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/generate', methods=['POST'])
def generate_bills():
    """Generate all PDFs"""
    global current_invoices
    
    if not current_invoices:
        return jsonify({'error': 'No invoices loaded'}), 400
    
    try:
        # Get paper settings from request
        data = request.get_json() or {}
        paper_size = data.get('paper_size', 'A5')
        orientation = data.get('orientation', 'portrait')
        starting_bill_str = str(data.get('starting_bill_number', '2600001'))
        bill_prefix, bill_start_num = parse_bill_number(starting_bill_str)

        # Stamp bill numbers once — invoice.bill_number and __bill_number__ column both set here.
        # PDF generator and sales report read these values; neither re-computes.
        _assign_bill_numbers(bill_prefix, bill_start_num)

        # Initialize PDF generator
        output_dir = app.config['OUTPUT_FOLDER']
        generator = PDFGenerator(output_dir)
        company = get_company_info()

        # Clean up old batch PDFs before generating new one
        for old_file in os.listdir(output_dir):
            if old_file.startswith('all_bills_') and old_file.endswith('.pdf'):
                os.remove(os.path.join(output_dir, old_file))

        # Generate all PDFs — invoice.bill_number is already set by _assign_bill_numbers above
        # pending_orders are prepended as a summary page (page 1) if any exist
        output_files = generator.generate_batch_bills(
            current_invoices, company, paper_size, orientation,
            pending_orders=current_pending_orders
        )

        # Verify the generated files actually exist
        existing_files = [f for f in output_files if os.path.exists(f)]
        if not existing_files:
            return jsonify({'error': 'PDF generation failed - no output files created'}), 500

        return jsonify({
            'success': True,
            'count': len(existing_files),
            'files': [os.path.basename(f) for f in existing_files],
            'message': f'Successfully generated {len(existing_files)} bills ({paper_size} {orientation})'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/debug-bills')
def debug_bills():
    """Return trimmed DataFrame bill assignment for debugging.

    Open http://localhost:5003/debug-bills after generating bills to inspect
    the full order → bill-number mapping as JSON.
    """
    if current_trimmed_df is None:
        return jsonify({'error': 'No data loaded. Upload and validate a CSV first.'}), 400
    cols = ['__bill_order__', '__bill_number__']
    for c in ['หมายเลขคำสั่งซื้อ', 'เวลาส่งสินค้า', 'ชื่อผู้รับ']:
        if c in current_trimmed_df.columns:
            cols.append(c)
    available = [c for c in cols if c in current_trimmed_df.columns]
    if '__bill_number__' not in available:
        return jsonify({'error': 'Bill numbers not yet assigned. Generate bills first.'}), 400
    df_debug = current_trimmed_df[available].drop_duplicates(subset=['__bill_order__']).fillna('').copy()
    return jsonify({
        'row_count': len(df_debug),
        'columns': available,
        'rows': df_debug.to_dict(orient='records')
    })


@app.route('/generate-one', methods=['POST'])
def generate_one_bill():
    """Generate single PDF (first invoice only)"""
    global current_invoices
    
    if not current_invoices:
        return jsonify({'error': 'No invoices loaded'}), 400
    
    try:
        # Get paper settings from request
        data = request.get_json() or {}
        paper_size = data.get('paper_size', 'A5')
        orientation = data.get('orientation', 'portrait')
        starting_bill_str = str(data.get('starting_bill_number', '2600001'))

        # Initialize PDF generator
        output_dir = app.config['OUTPUT_FOLDER']
        generator = PDFGenerator(output_dir)
        company = get_company_info()

        # Stamp bill numbers on all invoices (and DF) so all are consistent
        _bill_prefix, _bill_start = parse_bill_number(starting_bill_str)
        _assign_bill_numbers(_bill_prefix, _bill_start)

        # Generate first invoice only with paper settings
        output_path = generator.generate_single_bill(current_invoices[0], company, paper_size, orientation)
        filename = os.path.basename(output_path)

        return jsonify({
            'success': True,
            'filename': filename,
            'invoice_number': current_invoices[0].invoice_number,
            'message': f'Successfully generated bill for invoice {current_invoices[0].invoice_number} ({paper_size} {orientation})'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/generate-by-order', methods=['POST'])
def generate_by_order():
    """Generate PDF for specific order number or tax invoice number"""
    global current_invoices

    if not current_invoices:
        return jsonify({'error': 'No invoices loaded'}), 400

    try:
        data = request.get_json() or {}
        order_number = data.get('order_number', '').strip()
        paper_size = data.get('paper_size', 'A5')
        orientation = data.get('orientation', 'portrait')
        starting_bill_str = str(data.get('starting_bill_number', '2600001'))

        if not order_number:
            return jsonify({'error': 'Order number is required'}), 400

        # Find invoice with matching order number OR tax invoice number
        matching_invoice = None
        for invoice in current_invoices:
            if (str(invoice.order_id) == str(order_number) or
                str(invoice.invoice_number) == str(order_number)):
                matching_invoice = invoice
                break

        if not matching_invoice:
            return jsonify({'error': f'Order/Invoice number {order_number} not found'}), 404

        # Initialize PDF generator
        output_dir = app.config['OUTPUT_FOLDER']
        generator = PDFGenerator(output_dir)
        company = get_company_info()

        # Stamp bill numbers on all invoices (and DF) so all are consistent
        _bill_prefix, _bill_start = parse_bill_number(starting_bill_str)
        _assign_bill_numbers(_bill_prefix, _bill_start)

        # Generate bill with paper settings
        output_path = generator.generate_single_bill(matching_invoice, company, paper_size, orientation)
        filename = os.path.basename(output_path)
        
        return jsonify({
            'success': True,
            'filename': filename,
            'invoice_number': matching_invoice.invoice_number,
            'order_id': matching_invoice.order_id,
            'message': f'Successfully generated bill for order {matching_invoice.order_id} ({paper_size} {orientation})'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/download/<filename>')
def download_file(filename):
    """Download a single PDF"""
    filepath = os.path.join(app.config['OUTPUT_FOLDER'], filename)

    if not os.path.exists(filepath):
        return jsonify({'error': f'File not found: {filename}'}), 404

    with open(filepath, 'rb') as f:
        pdf_bytes = f.read()

    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/download-all')
def download_all():
    """Download the batch-generated PDF file"""
    try:
        output_dir = app.config['OUTPUT_FOLDER']

        # Find the most recent all_bills PDF by modification time
        pdf_files = [f for f in os.listdir(output_dir) if f.startswith('all_bills_') and f.endswith('.pdf')]

        if not pdf_files:
            return jsonify({'error': 'No batch PDF found. Please generate bills first.'}), 404

        # Sort by modification time (newest first)
        pdf_files.sort(key=lambda f: os.path.getmtime(os.path.join(output_dir, f)), reverse=True)
        latest_pdf = pdf_files[0]
        filepath = os.path.join(output_dir, latest_pdf)

        # Read file bytes directly to bypass any caching
        with open(filepath, 'rb') as f:
            pdf_bytes = f.read()

        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename={latest_pdf}'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _build_sales_data(df, preset, mapping, invoice_lookup, bill_prefix, starting_bill_number):
    """Build sales report rows from the trimmed dataframe.

    Returns a dict containing report_rows (list of dicts), per-order summary dicts,
    seen_orders (set), total_qty (float), and model_stats (dict).
    """
    order_col = mapping.get('order_id', 'หมายเลขคำสั่งซื้อ')
    product_col = mapping.get('product_name', 'ชื่อสินค้า')
    sale_price_col = mapping.get('sale_price', 'ราคาขาย')
    qty_col = mapping.get('quantity', 'จำนวน')
    estimated_shipping_col = mapping.get('estimated_shipping', 'ค่าจัดส่งโดยประมาณ')
    option_name_col = mapping.get('variant', 'ชื่อตัวเลือก')
    shopee_discount_col = mapping.get('shopee_discount', 'ส่วนลดจาก Shopee')
    recipient_col = mapping.get('recipient_name', 'ชื่อผู้รับ')

    def find_col(name):
        stripped_cols = {c.strip(): c for c in df.columns}
        if name in stripped_cols:
            return stripped_cols[name]
        for col_stripped, col_orig in stripped_cols.items():
            if name in col_stripped:
                return col_orig
        return None

    seller_discount_code_col = find_col('โค้ดส่วนลดชำระโดยผู้ขาย')
    commission_col = find_col('ค่าคอมมิชชั่น')
    transaction_fee_col = find_col('Transaction Fee')
    buyer_paid_col = find_col('ราคาสินค้าที่ชำระโดยผู้ซื้อ')
    net_sale_col = find_col('ราคาขายสุทธิ')
    shopee_shipping_col = find_col('ค่าจัดส่งที่ Shopee ออกให้โดยประมาณ')

    seller_disc_other_cols = [c for c in (find_col(n) for n in [
        'โค้ด coins Cashback ชำระโดยผู้ขาย',
        'ส่วนลด bundle deal ชำระโดยผู้ขาย',
        'โบนัสส่วนลดเครื่องเก่าแลกใหม่จากผู้ขาย',
    ]) if c]

    shopee_disc_other_cols = [c for c in (find_col(n) for n in [
        'โค้ดส่วนลดชำระโดย Shopee',
        'ส่วนลด bundle deal ชำระโดย Shopee',
        'ส่วนลดจากการใช้เหรียญ',
        'โปรโมชั่นช่องทางชำระเงินทั้งหมด',
        'ส่วนลดเครื่องเก่าแลกใหม่',
        'โบนัสส่วนลดเครื่องเก่าแลกใหม่',
    ]) if c]

    def extract_model(product_name):
        if pd.isna(product_name):
            return ''
        match = re.search(r'รุ่น\s+(\S+)', str(product_name))
        return match.group(1) if match else ''

    def extract_color(option_name):
        if pd.isna(option_name) or not str(option_name).strip():
            return ''
        parts = str(option_name).split(',', 1)
        return parts[0].strip() if parts else ''

    def extract_size(option_name):
        if pd.isna(option_name) or not str(option_name).strip():
            return ''
        parts = str(option_name).split(',', 1)
        if len(parts) < 2:
            return ''
        size_part = parts[1].strip()
        match = re.match(r'#?(\d+)', size_part)
        return match.group(0) if match else size_part

    def clean_num(val):
        if pd.isna(val) or val == '' or val == '-':
            return 0.0
        if isinstance(val, str):
            val = val.strip().replace(',', '').replace(' ', '')
            if val == '' or val == '-':
                return 0.0
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    def safe_col_val(row, col_name):
        if col_name and col_name in row.index:
            return clean_num(row.get(col_name, 0))
        return 0.0

    # Pre-compute per-order sums for multi-row discount columns
    order_seller_disc_main_pre = {}
    order_seller_disc_other_pre = {}
    order_shopee_disc_other_pre = {}
    for oid_val, grp in df.groupby(order_col, sort=False):
        oid_str = str(oid_val)
        if seller_discount_code_col and seller_discount_code_col in df.columns:
            order_seller_disc_main_pre[oid_str] = sum(clean_num(v) for v in grp[seller_discount_code_col])
        else:
            order_seller_disc_main_pre[oid_str] = 0.0
        order_seller_disc_other_pre[oid_str] = sum(
            sum(clean_num(v) for v in grp[c]) for c in seller_disc_other_cols if c in df.columns
        )
        order_shopee_disc_other_pre[oid_str] = sum(
            sum(clean_num(v) for v in grp[c]) for c in shopee_disc_other_cols if c in df.columns
        )

    # Sort rows by the pre-locked bill order stamped at processing time.
    # __bill_order__ is an integer (0-based order_index) already written into the df
    # by save-mapping / apply-return-decisions, so no re-computation needed here.
    if '__bill_order__' in df.columns:
        df = df.sort_values(by='__bill_order__', kind='stable', na_position='last').reset_index(drop=True)

    report_rows = []
    seen_orders = set()
    order_shipping_buyer = {}
    order_service_fee = {}
    order_grand_total = {}
    order_estimated_shipping = {}
    order_seller_disc_main = {}
    order_seller_disc_other = {}
    order_shopee_disc_main = {}
    order_shopee_disc_other = {}
    order_shopee_shipping = {}
    order_buyer_paid = {}
    order_commission = {}
    order_transaction_fee = {}
    order_total_fee = {}
    order_actual_receive = {}
    total_qty = 0.0
    row_number = 0
    model_stats = {}

    for _, row in df.iterrows():
        oid = str(row[order_col]) if pd.notna(row[order_col]) else ''
        model = extract_model(row.get(product_col, ''))
        sale_price = clean_num(row.get(sale_price_col, 0))
        if preset and preset.implicit_quantity is not None:
            qty = float(preset.implicit_quantity)
        else:
            qty = clean_num(row.get(qty_col, 0)) if qty_col in df.columns else 1.0
        total_qty += qty
        row_number += 1

        option_val = row.get(option_name_col, '') if option_name_col in df.columns else ''
        color = extract_color(option_val)
        size = extract_size(option_val)

        if model:
            if model not in model_stats:
                model_stats[model] = {'total_value': 0.0, 'total_qty': 0.0, 'prices': []}
            model_stats[model]['total_value'] += sale_price * qty
            model_stats[model]['total_qty'] += qty
            model_stats[model]['prices'].append(sale_price)

        net_sale = clean_num(row.get(net_sale_col, 0)) if net_sale_col and net_sale_col in df.columns else (sale_price * qty)

        is_first_row = oid not in seen_orders
        if is_first_row:
            seen_orders.add(oid)
            inv_data = invoice_lookup.get(oid, {})
            # Read bill number from pre-stamped DF column — no re-computation
            if '__bill_number__' in df.columns:
                bill_num = str(row.get('__bill_number__', ''))
            else:
                bill_num = format_bill_number(bill_prefix, starting_bill_number + inv_data.get('order_index', 0))
            sb = inv_data.get('shipping', 0.0)
            sf = inv_data.get('service_fee', 0.0)
            gt = inv_data.get('grand_total', 0.0)
            es = clean_num(row.get(estimated_shipping_col, 0)) if estimated_shipping_col in df.columns else 0.0
            vat_amt = inv_data.get('vat_amount', 0.0)
            before_vat = inv_data.get('total_before_vat', 0.0)
            recipient = str(row.get(recipient_col, '')) if recipient_col in df.columns else ''
            sd_main = order_seller_disc_main_pre.get(oid, 0.0)
            sd_other = order_seller_disc_other_pre.get(oid, 0.0)
            shopee_disc_main = clean_num(row.get(shopee_discount_col, 0)) if shopee_discount_col in df.columns else 0.0
            shopee_disc_other = order_shopee_disc_other_pre.get(oid, 0.0)
            shopee_ship = clean_num(row.get(shopee_shipping_col, 0)) if shopee_shipping_col and shopee_shipping_col in df.columns else 0.0
            comm_fee = safe_col_val(row, commission_col)
            trans_fee = safe_col_val(row, transaction_fee_col)
            svc_fee_val = sf
            total_fee = comm_fee + trans_fee + svc_fee_val
            buyer_paid = safe_col_val(row, buyer_paid_col)
            actual_receive = buyer_paid + shopee_disc_main - total_fee - sb

            order_shipping_buyer[oid] = sb
            order_service_fee[oid] = sf
            order_grand_total[oid] = gt
            order_estimated_shipping[oid] = es
            order_seller_disc_main[oid] = sd_main
            order_seller_disc_other[oid] = sd_other
            order_shopee_disc_main[oid] = shopee_disc_main
            order_shopee_disc_other[oid] = shopee_disc_other
            order_shopee_shipping[oid] = shopee_ship
            order_buyer_paid[oid] = buyer_paid
            order_commission[oid] = comm_fee
            order_transaction_fee[oid] = trans_fee
            order_total_fee[oid] = total_fee
            order_actual_receive[oid] = actual_receive
        else:
            bill_num = ''
            recipient = ''
            sb = sf = gt = es = vat_amt = before_vat = None
            sd_main = sd_other = shopee_disc_main = shopee_disc_other = shopee_ship = None
            comm_fee = trans_fee = svc_fee_val = total_fee = buyer_paid = actual_receive = None

        report_rows.append({
            'row_num': row_number,
            'bill_number': bill_num,
            'recipient': recipient,
            'order_id': oid if is_first_row else '',
            'model': model,
            'color': color,
            'size': size,
            'sale_price': sale_price,
            'qty': qty,
            'net_sale': net_sale,
            'seller_disc_main': sd_main,
            'seller_disc_other': sd_other,
            'shopee_disc_main': shopee_disc_main,
            'shopee_disc_other': shopee_disc_other,
            'shipping_buyer': sb,
            'shopee_shipping': shopee_ship,
            'buyer_paid': buyer_paid,
            'estimated_shipping': es,
            'grand_total': gt,
            'vat_amount': vat_amt,
            'total_before_vat': before_vat,
            'commission': comm_fee,
            'transaction_fee': trans_fee,
            'service_fee': sf,
            'total_fee': total_fee,
            'actual_receive': actual_receive,
        })

    return {
        'report_rows': report_rows,
        'seen_orders': seen_orders,
        'total_qty': total_qty,
        'model_stats': model_stats,
        'order_shipping_buyer': order_shipping_buyer,
        'order_service_fee': order_service_fee,
        'order_grand_total': order_grand_total,
        'order_estimated_shipping': order_estimated_shipping,
        'order_seller_disc_main': order_seller_disc_main,
        'order_seller_disc_other': order_seller_disc_other,
        'order_shopee_disc_main': order_shopee_disc_main,
        'order_shopee_disc_other': order_shopee_disc_other,
        'order_shopee_shipping': order_shopee_shipping,
        'order_buyer_paid': order_buyer_paid,
        'order_commission': order_commission,
        'order_transaction_fee': order_transaction_fee,
        'order_total_fee': order_total_fee,
        'order_actual_receive': order_actual_receive,
    }


@app.route('/sales-report', methods=['POST'])
def sales_report():
    """Generate sales report PDF from trimmed data"""
    global current_trimmed_df

    if current_trimmed_df is None or current_trimmed_df.empty:
        return jsonify({'error': 'No data available. Please upload and process a CSV first.'}), 400

    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        # Register Thai font (OS-aware paths)
        import sys as _sys
        _tahoma = _tahoma_bold = None
        if _sys.platform == 'win32':
            _candidates      = [r'C:\Windows\Fonts\tahoma.ttf',   r'C:\Windows\Fonts\Tahoma.ttf']
            _candidates_bold = [r'C:\Windows\Fonts\tahomabd.ttf', r'C:\Windows\Fonts\Tahomabd.ttf']
        else:
            _candidates      = ['/System/Library/Fonts/Supplemental/Tahoma.ttf', '/Library/Fonts/Tahoma.ttf']
            _candidates_bold = ['/System/Library/Fonts/Supplemental/Tahoma Bold.ttf', '/Library/Fonts/Tahoma Bold.ttf']
        import os as _os
        for _p in _candidates:
            if _os.path.exists(_p): _tahoma = _p; break
        for _p in _candidates_bold:
            if _os.path.exists(_p): _tahoma_bold = _p; break
        try:
            if not _tahoma: raise FileNotFoundError
            pdfmetrics.registerFont(TTFont('ThaiFont', _tahoma))
            pdfmetrics.registerFont(TTFont('ThaiFont-Bold', _tahoma_bold or _tahoma))
            thai_font = 'ThaiFont'
            thai_font_bold = 'ThaiFont-Bold'
        except Exception:
            thai_font = 'Helvetica'
            thai_font_bold = 'Helvetica-Bold'

        data = request.get_json() or {}
        starting_bill_str = str(data.get('starting_bill_number', '2600001'))
        bill_prefix, starting_bill_number = parse_bill_number(starting_bill_str)

        # Stamp bill numbers once — same helper as /generate, so numbers are guaranteed identical
        _assign_bill_numbers(bill_prefix, starting_bill_number)

        if current_platform:
            parser = _make_parser()
        else:
            parser = _make_parser(custom_column_map=config.get('column_mapping'))
        mapping = parser.column_map
        df = current_trimmed_df.copy()

        invoice_lookup = {
            inv.order_id: {
                'shipping': inv.shipping, 'service_fee': inv.service_fee,
                'grand_total': inv.grand_total, 'discount': inv.discount,
                'subtotal': inv.subtotal, 'vat_amount': inv.vat_amount,
                'total_before_vat': inv.total_before_vat,
                'order_sort_key': inv.order_sort_key,
                'order_index': inv.order_index,
            }
            for inv in current_invoices
        }

        sd = _build_sales_data(df, _get_platform_preset(), mapping, invoice_lookup, bill_prefix, starting_bill_number)
        report_rows = sd['report_rows']
        seen_orders = sd['seen_orders']
        total_qty = sd['total_qty']
        model_stats = sd['model_stats']
        order_shipping_buyer = sd['order_shipping_buyer']
        order_service_fee = sd['order_service_fee']
        order_grand_total = sd['order_grand_total']
        order_estimated_shipping = sd['order_estimated_shipping']
        order_seller_disc_main = sd['order_seller_disc_main']
        order_seller_disc_other = sd['order_seller_disc_other']
        order_shopee_disc_main = sd['order_shopee_disc_main']
        order_shopee_disc_other = sd['order_shopee_disc_other']
        order_shopee_shipping = sd['order_shopee_shipping']
        order_buyer_paid = sd['order_buyer_paid']
        order_commission = sd['order_commission']
        order_transaction_fee = sd['order_transaction_fee']
        order_total_fee = sd['order_total_fee']
        order_actual_receive = sd['order_actual_receive']

        # Build PDF — landscape A4 to accommodate more columns
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=14, rightMargin=14, topMargin=40, bottomMargin=30)

        title_style = ParagraphStyle('Title', fontName=thai_font_bold, fontSize=14, leading=18, alignment=0)
        header_style = ParagraphStyle('Header', fontName=thai_font_bold, fontSize=6, leading=8, alignment=1)
        cell_style = ParagraphStyle('Cell', fontName=thai_font, fontSize=6, leading=8)
        cell_center = ParagraphStyle('CellCenter', fontName=thai_font, fontSize=6, leading=8, alignment=1)
        cell_right = ParagraphStyle('CellRight', fontName=thai_font, fontSize=6, leading=8, alignment=2)

        elements = []
        elements.append(Paragraph('Sales Report (รายงานยอดขาย)', title_style))
        elements.append(Spacer(1, 12))

        # Table header — 26 columns (landscape layout)
        headers = [
            Paragraph('ลำดับ', header_style),
            Paragraph('เลขที่บิล', header_style),
            Paragraph('ชื่อผู้รับ', header_style),
            Paragraph('หมายเลข\nคำสั่งซื้อ', header_style),
            Paragraph('รหัส\nสินค้า', header_style),
            Paragraph('ตัวเลือก\n(สี)', header_style),
            Paragraph('ตัวเลือก\n(ขนาด)', header_style),
            Paragraph('ราคาขาย', header_style),
            Paragraph('จำนวน', header_style),
            Paragraph('รวมเป็นเงิน', header_style),
            Paragraph('ส่วนลด\nผู้ขาย', header_style),
            Paragraph('ส่วนลดอื่นๆ\nผู้ขาย', header_style),
            Paragraph('ส่วนลด\nShopee', header_style),
            Paragraph('ส่วนลดอื่นๆ\nShopee', header_style),
            Paragraph('ค่าจัดส่ง\n(ผู้ซื้อ)', header_style),
            Paragraph('ค่าจัดส่ง\nShopee', header_style),
            Paragraph('ราคาสินค้า\nชำระโดยผู้ซื้อ', header_style),
            Paragraph('ค่าจัดส่ง\nประมาณ', header_style),
            Paragraph('จำนวนเงิน\nทั้งหมด', header_style),
            Paragraph('VAT 7%', header_style),
            Paragraph('ยอดก่อน\nVAT', header_style),
            Paragraph('ค่าคอม', header_style),
            Paragraph('Transaction\nFee', header_style),
            Paragraph('ค่าบริการ', header_style),
            Paragraph('ค่าธรรม\nเนียม', header_style),
            Paragraph('จำนวนเงิน\nได้รับจริง', header_style),
        ]

        def fmt(val):
            if val is None:
                return ''
            return f'{val:,.2f}'

        table_data = [headers]
        for r in report_rows:
            qty_val = r['qty']
            qty_str = str(int(qty_val)) if qty_val == int(qty_val) else fmt(qty_val)
            table_data.append([
                Paragraph(str(r['row_num']), cell_center),
                Paragraph(r['bill_number'], cell_center),
                Paragraph(r['recipient'], cell_style),
                Paragraph(r['order_id'], cell_style),
                Paragraph(r['model'], cell_style),
                Paragraph(r['color'], cell_style),
                Paragraph(r['size'], cell_center),
                Paragraph(fmt(r['sale_price']), cell_right),
                Paragraph(qty_str, cell_right),
                Paragraph(fmt(r['net_sale']), cell_right),
                Paragraph(fmt(r['seller_disc_main']), cell_right),
                Paragraph(fmt(r['seller_disc_other']), cell_right),
                Paragraph(fmt(r['shopee_disc_main']), cell_right),
                Paragraph(fmt(r['shopee_disc_other']), cell_right),
                Paragraph(fmt(r['shipping_buyer']), cell_right),
                Paragraph(fmt(r['shopee_shipping']), cell_right),
                Paragraph(fmt(r['buyer_paid']), cell_right),
                Paragraph(fmt(r['estimated_shipping']), cell_right),
                Paragraph(fmt(r['grand_total']), cell_right),
                Paragraph(fmt(r['vat_amount']), cell_right),
                Paragraph(fmt(r['total_before_vat']), cell_right),
                Paragraph(fmt(r['commission']), cell_right),
                Paragraph(fmt(r['transaction_fee']), cell_right),
                Paragraph(fmt(r['service_fee']), cell_right),
                Paragraph(fmt(r['total_fee']), cell_right),
                Paragraph(fmt(r['actual_receive']), cell_right),
            ])

        # Landscape A4 usable width: ~814pt (842 - 2*14 margins)
        # 26 cols total = 784pt
        col_widths = [14, 34, 38, 54, 30, 40, 18, 28, 18, 32,
                      30, 30, 28, 30, 30, 30, 36, 28, 34, 26,
                      30, 28, 28, 24, 30, 36]
        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), thai_font),
            ('FONTSIZE', (0, 0), (-1, -1), 6),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a90d9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (7, 1), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f4f8')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(t)

        # Page break before summary
        elements.append(PageBreak())

        # Summary table
        sum_title_style = ParagraphStyle('SumTitle', fontName=thai_font_bold, fontSize=11, leading=14)
        elements.append(Paragraph('Summary (สรุป)', sum_title_style))
        elements.append(Spacer(1, 8))

        sum_shipping_buyer = sum(order_shipping_buyer.values())
        sum_service_fee = sum(order_service_fee.values())
        sum_grand_total = sum(order_grand_total.values())
        sum_estimated_shipping = sum(order_estimated_shipping.values())
        sum_seller_disc_main = sum(order_seller_disc_main.values())
        sum_seller_disc_other = sum(order_seller_disc_other.values())
        sum_shopee_disc_main = sum(order_shopee_disc_main.values())
        sum_shopee_disc_other = sum(order_shopee_disc_other.values())
        sum_shopee_shipping = sum(order_shopee_shipping.values())
        sum_buyer_paid = sum(order_buyer_paid.values())
        sum_commission = sum(order_commission.values())
        sum_transaction_fee = sum(order_transaction_fee.values())
        sum_total_fee = sum(order_total_fee.values())
        sum_actual_receive = sum(order_actual_receive.values())

        # Sum VAT from pre-computed invoice values
        sum_vat = sum(inv.vat_amount for inv in current_invoices)
        sum_before_vat = sum(inv.total_before_vat for inv in current_invoices)

        summary_data = [
            [Paragraph('รายการ', header_style), Paragraph('ยอดรวม', header_style)],
            [Paragraph('จำนวนคำสั่งซื้อ', cell_style), Paragraph(f'{len(seen_orders):,}', cell_right)],
            [Paragraph('จำนวนสินค้า (ชิ้น)', cell_style), Paragraph(f'{int(total_qty):,}', cell_right)],
            [Paragraph('ส่วนลดโดยผู้ขาย', cell_style), Paragraph(fmt(sum_seller_disc_main), cell_right)],
            [Paragraph('ส่วนลดอื่นๆ โดยผู้ขาย', cell_style), Paragraph(fmt(sum_seller_disc_other), cell_right)],
            [Paragraph('ส่วนลดโดย Shopee', cell_style), Paragraph(fmt(sum_shopee_disc_main), cell_right)],
            [Paragraph('ส่วนลดอื่นๆ โดย Shopee', cell_style), Paragraph(fmt(sum_shopee_disc_other), cell_right)],
            [Paragraph('ค่าจัดส่ง (ผู้ซื้อ)', cell_style), Paragraph(fmt(sum_shipping_buyer), cell_right)],
            [Paragraph('ค่าจัดส่งโดย Shopee', cell_style), Paragraph(fmt(sum_shopee_shipping), cell_right)],
            [Paragraph('ราคาสินค้าชำระโดยผู้ซื้อ', cell_style), Paragraph(fmt(sum_buyer_paid), cell_right)],
            [Paragraph('ค่าจัดส่งโดยประมาณ', cell_style), Paragraph(fmt(sum_estimated_shipping), cell_right)],
            [Paragraph('จำนวนเงินทั้งหมด', cell_style), Paragraph(fmt(sum_grand_total), cell_right)],
            [Paragraph('ยอดก่อน VAT', cell_style), Paragraph(fmt(sum_before_vat), cell_right)],
            [Paragraph('VAT 7%', cell_style), Paragraph(fmt(sum_vat), cell_right)],
            [Paragraph('ค่าคอมมิชชั่น', cell_style), Paragraph(fmt(sum_commission), cell_right)],
            [Paragraph('Transaction Fee', cell_style), Paragraph(fmt(sum_transaction_fee), cell_right)],
            [Paragraph('ค่าบริการ', cell_style), Paragraph(fmt(sum_service_fee), cell_right)],
            [Paragraph('ค่าธรรมเนียมรวม', cell_style), Paragraph(fmt(sum_total_fee), cell_right)],
            [Paragraph('จำนวนเงินที่ได้รับจริง', cell_style), Paragraph(fmt(sum_actual_receive), cell_right)],
        ]

        st = Table(summary_data, colWidths=[200, 120])
        st.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), thai_font),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a90d9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f4f8')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(st)

        # Top 10 Models by Sales Value
        elements.append(Spacer(1, 24))
        elements.append(Paragraph('Top 10 Models by Sales Value (สินค้าขายดี 10 อันดับ)', sum_title_style))
        elements.append(Spacer(1, 8))

        # Calculate total sales value across all models
        total_sales_value = sum(m['total_value'] for m in model_stats.values())

        # Sort models by total_value descending, take top 10
        top_models = sorted(model_stats.items(), key=lambda x: x[1]['total_value'], reverse=True)[:10]

        top_header_style = ParagraphStyle('TopHeader', fontName=thai_font_bold, fontSize=8, leading=10, alignment=1)
        top_cell = ParagraphStyle('TopCell', fontName=thai_font, fontSize=8, leading=10)
        top_cell_right = ParagraphStyle('TopCellRight', fontName=thai_font, fontSize=8, leading=10, alignment=2)
        top_cell_center = ParagraphStyle('TopCellCenter', fontName=thai_font, fontSize=8, leading=10, alignment=1)

        top_data = [[
            Paragraph('#', top_header_style),
            Paragraph('Model', top_header_style),
            Paragraph('ราคาเฉลี่ย', top_header_style),
            Paragraph('จำนวนขาย', top_header_style),
            Paragraph('ยอดขาย', top_header_style),
            Paragraph('% ของยอดรวม', top_header_style),
        ]]

        for rank, (model_name, stats) in enumerate(top_models, 1):
            avg_price = sum(stats['prices']) / len(stats['prices']) if stats['prices'] else 0
            pct = (stats['total_value'] / total_sales_value * 100) if total_sales_value > 0 else 0
            top_data.append([
                Paragraph(str(rank), top_cell_center),
                Paragraph(model_name, top_cell),
                Paragraph(fmt(avg_price), top_cell_right),
                Paragraph(f'{int(stats["total_qty"]):,}', top_cell_right),
                Paragraph(fmt(stats['total_value']), top_cell_right),
                Paragraph(f'{pct:.1f}%', top_cell_right),
            ])

        top_table = Table(top_data, colWidths=[25, 80, 80, 65, 90, 80])
        top_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), thai_font),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a90d9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f4f8')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(top_table)

        doc.build(elements)
        buffer.seek(0)

        response = make_response(buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'attachment; filename=sales_report.pdf'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/sales-report-export', methods=['POST'])
def sales_report_export():
    """Export sales report as CSV or XLSX"""
    global current_trimmed_df

    if current_trimmed_df is None or current_trimmed_df.empty:
        return jsonify({'error': 'No data available. Please upload and process a CSV first.'}), 400

    try:
        data = request.get_json() or {}
        fmt = data.get('format', 'csv').lower()
        starting_bill_str = str(data.get('starting_bill_number', '2600001'))
        bill_prefix, starting_bill_number = parse_bill_number(starting_bill_str)

        if current_platform:
            parser = _make_parser()
        else:
            parser = _make_parser(custom_column_map=config.get('column_mapping'))
        mapping = parser.column_map
        df = current_trimmed_df.copy()

        invoice_lookup = {
            inv.order_id: {
                'shipping': inv.shipping, 'service_fee': inv.service_fee,
                'grand_total': inv.grand_total, 'discount': inv.discount,
                'subtotal': inv.subtotal, 'vat_amount': inv.vat_amount,
                'total_before_vat': inv.total_before_vat,
                'order_sort_key': inv.order_sort_key,
                'order_index': inv.order_index,
            }
            for inv in current_invoices
        }

        sd = _build_sales_data(df, _get_platform_preset(), mapping, invoice_lookup, bill_prefix, starting_bill_number)
        report_rows = sd['report_rows']

        # Thai column headers matching the 26-column PDF layout
        col_map = {
            'row_num':          'ลำดับ',
            'bill_number':      'เลขที่บิล',
            'recipient':        'ชื่อผู้รับ',
            'order_id':         'หมายเลขคำสั่งซื้อ',
            'model':            'รหัสสินค้า',
            'color':            'ตัวเลือก (สี)',
            'size':             'ตัวเลือก (ขนาด)',
            'sale_price':       'ราคาขาย',
            'qty':              'จำนวนสินค้า',
            'net_sale':         'รวมเป็นเงิน',
            'seller_disc_main': 'ส่วนลดโดยผู้ขาย',
            'seller_disc_other':'ส่วนลดอื่นๆ โดยผู้ขาย',
            'shopee_disc_main': 'ส่วนลดโดย Shopee',
            'shopee_disc_other':'ส่วนลดอื่นๆ โดย Shopee',
            'shipping_buyer':   'ค่าจัดส่ง (ผู้ซื้อ)',
            'shopee_shipping':  'ค่าจัดส่งโดย Shopee',
            'buyer_paid':       'ราคาสินค้าที่ชำระโดยผู้ซื้อ',
            'estimated_shipping':'ค่าจัดส่งประมาณ',
            'grand_total':      'จำนวนเงินทั้งหมด',
            'vat_amount':       'VAT 7%',
            'total_before_vat': 'ยอดก่อน VAT',
            'commission':       'ค่าคอมมิชชั่น',
            'transaction_fee':  'Transaction Fee',
            'service_fee':      'ค่าบริการ',
            'total_fee':        'ค่าธรรมเนียม',
            'actual_receive':   'จำนวนเงินที่ได้รับจริง',
        }

        export_df = pd.DataFrame(report_rows)[list(col_map.keys())]
        export_df.rename(columns=col_map, inplace=True)

        buffer = BytesIO()
        if fmt == 'xlsx':
            export_df.to_excel(buffer, index=False, engine='openpyxl')
            buffer.seek(0)
            resp = make_response(buffer.read())
            resp.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            resp.headers['Content-Disposition'] = 'attachment; filename=sales_report.xlsx'
        else:
            csv_str = export_df.to_csv(index=False, encoding='utf-8-sig')
            resp = make_response(csv_str.encode('utf-8-sig'))
            resp.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
            resp.headers['Content-Disposition'] = 'attachment; filename=sales_report.csv'

        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/sort-csv', methods=['POST'])
def sort_csv():
    """Re-sort processed CSV in bill-generation order, grouped by invoice (original columns only)."""
    global current_invoices, current_trimmed_df

    if not current_invoices:
        return jsonify({'error': 'No invoices loaded. Please process a CSV first.'}), 400
    if current_trimmed_df is None or current_trimmed_df.empty:
        return jsonify({'error': 'No CSV data available.'}), 400

    try:
        # Determine the column used to group rows by invoice
        parser = _make_parser()
        tax_invoice_col = parser.column_map.get('tax_invoice') or parser.column_map.get('order_id')

        df = current_trimmed_df.copy()

        # For each invoice in bill-generation order, collect its rows from the df
        sorted_parts = []
        for invoice in current_invoices:
            mask = df[tax_invoice_col].astype(str).str.strip() == str(invoice.invoice_number).strip()
            inv_rows = df[mask].copy()
            if inv_rows.empty:
                continue
            sorted_parts.append(inv_rows)

        if not sorted_parts:
            return jsonify({'error': 'Could not match any CSV rows to invoices.'}), 400

        result_df = pd.concat(sorted_parts, ignore_index=True)
        # Ensure all columns stay as strings so Excel never converts them to numbers
        result_df = result_df.astype(str).replace({'nan': '', 'None': ''})

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            result_df.to_excel(writer, index=False, sheet_name='Sorted Bills')
            ws = writer.sheets['Sorted Bills']
            # Force every data cell to Text format so Excel shows full IDs, not 5.82E+17
            from openpyxl.styles import numbers as xl_numbers
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=ws.max_column):
                for cell in row:
                    cell.number_format = '@'
        buf.seek(0)

        resp = make_response(buf.read())
        resp.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        resp.headers['Content-Disposition'] = 'attachment; filename=sorted_bills.xlsx'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/stats')
def get_stats():
    """Get current statistics"""
    global current_invoices
    
    return jsonify({
        'invoice_count': len(current_invoices),
        'output_folder': app.config['OUTPUT_FOLDER']
    })


if __name__ == '__main__':
    # Auto-open browser
    import webbrowser
    import threading

    # Only open browser on first run, not on reloader restarts
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        def open_browser():
            webbrowser.open('http://localhost:5003')
        threading.Timer(1.5, open_browser).start()

    # Run Flask
    app.run(debug=True, port=5003, host='0.0.0.0')
