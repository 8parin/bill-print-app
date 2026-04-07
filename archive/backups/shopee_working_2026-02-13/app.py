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
from src.pdf_generator_reportlab import PDFGeneratorReportLab as PDFGenerator
from src.bill_data import CompanyInfo

app = Flask(__name__)

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
    global current_invoices, current_csv_path
    
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
        
        # Detect columns
        parser = CSVParser(
            vat_rate=config['settings']['vat_rate'],
            custom_column_map=config.get('column_mapping')
        )
        detected_columns = parser.detect_columns(filepath)
        
        # Validate format (check if CSV structure matches expected format)
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
            'column_diff': column_diff
        }
        
        # If format has changed, warn the user
        if not format_valid:
            response_data['warning'] = True
            response_data['message'] = 'CSV uploaded, but format has changed. Please verify column mapping.'

        # Flag if first column is corrupted
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
    parser = CSVParser()
    return jsonify({
        'fields': parser.get_field_definitions(),
        'required_fields': parser.REQUIRED_FIELDS,
        'current_mapping': config.get('column_mapping', parser.COLUMN_MAP)
    })


@app.route('/save-mapping', methods=['POST'])
def save_mapping():
    """Save custom column mapping"""
    global current_invoices, current_csv_path, current_trimmed_df
    
    try:
        mapping = request.json.get('mapping', {})
        
        # Validate mapping
        parser = CSVParser()
        valid, errors = parser.validate_mapping(mapping)
        
        if not valid:
            return jsonify({'error': 'Invalid mapping', 'details': errors}), 400
        
        # Save to config
        config['column_mapping'] = mapping
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        # Parse CSV with new mapping
        # If current_csv_path is None (server restarted), find the most recent upload
        csv_path = current_csv_path
        if not csv_path:
            upload_dir = app.config['UPLOAD_FOLDER']
            csv_files = [f for f in os.listdir(upload_dir) if f.endswith('.csv')]
            if csv_files:
                # Use the most recently modified CSV
                csv_files.sort(key=lambda f: os.path.getmtime(os.path.join(upload_dir, f)), reverse=True)
                csv_path = os.path.join(upload_dir, csv_files[0])
                current_csv_path = csv_path

        if csv_path:
            parser_with_mapping = CSVParser(
                vat_rate=config['settings']['vat_rate'],
                custom_column_map=mapping
            )

            # Read and filter cancelled orders first
            df = parser_with_mapping.read_csv(csv_path)
            df, cancelled_count = parser_with_mapping.filter_cancelled_invoices(df)

            # Check for return items before parsing invoices
            return_items = parser_with_mapping.detect_return_items(df)

            if return_items:
                # Returns found — send them for user review before proceeding
                msg = f'Mapping saved! Found return/refund items that need review.'
                if cancelled_count > 0:
                    msg += f' ({cancelled_count} cancelled invoice(s) already filtered out)'

                return jsonify({
                    'success': True,
                    'needs_return_review': True,
                    'return_items': return_items,
                    'cancelled_count': cancelled_count,
                    'message': msg
                })
            else:
                # No returns — parse invoices directly
                # Store trimmed df for sales report (forward-fill applied)
                current_trimmed_df = df.copy()
                for fld in ['order_id', 'tax_invoice', 'order_date', 'recipient_name', 'phone', 'address',
                            'tracking_number', 'shopee_discount', 'shipping_buyer', 'service_fee', 'grand_total', 'estimated_shipping']:
                    col = parser_with_mapping.column_map.get(fld)
                    if col and col in current_trimmed_df.columns:
                        current_trimmed_df[col] = current_trimmed_df[col].replace('', pd.NA)
                        current_trimmed_df[col] = current_trimmed_df[col].ffill()

                current_invoices = parser_with_mapping.parse_csv_to_invoices(csv_path)
                cancelled = getattr(parser_with_mapping, 'last_cancelled_count', 0)

                msg = f'Mapping saved! Found {len(current_invoices)} invoices.'
                if cancelled > 0:
                    msg += f' ({cancelled} cancelled invoice(s) filtered out)'

                return jsonify({
                    'success': True,
                    'invoice_count': len(current_invoices),
                    'cancelled_count': cancelled,
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
    global current_invoices, current_csv_path, current_trimmed_df

    try:
        data = request.get_json() or {}
        decisions = data.get('decisions', [])

        csv_path = current_csv_path
        if not csv_path:
            return jsonify({'error': 'No CSV file loaded. Please upload a CSV first.'}), 400

        mapping = config.get('column_mapping', CSVParser.COLUMN_MAP)
        parser = CSVParser(
            vat_rate=config['settings']['vat_rate'],
            custom_column_map=mapping
        )

        # Read CSV and filter cancelled orders
        df = parser.read_csv(csv_path)
        df, cancelled_count = parser.filter_cancelled_invoices(df)

        # Apply return decisions
        df = parser.apply_return_decisions(df, decisions)

        # Store trimmed df for sales report
        current_trimmed_df = df.copy()

        # Count how many items were removed
        removed_products = sum(1 for d in decisions if d.get('action') == 'remove_product')
        removed_bills = sum(1 for d in decisions if d.get('action') == 'remove_bill')

        # Now group and parse invoices from the filtered DataFrame
        grouped = parser.group_by_invoice(df)
        current_invoices = []
        for invoice_num, invoice_df in grouped.items():
            try:
                invoice = parser.parse_invoice(invoice_df, invoice_num)
                current_invoices.append(invoice)
            except Exception as e:
                print(f"Warning: Failed to parse invoice {invoice_num}: {e}")
                continue

        msg = f'Found {len(current_invoices)} invoices.'
        parts = []
        if cancelled_count > 0:
            parts.append(f'{cancelled_count} cancelled')
        if removed_products > 0:
            parts.append(f'{removed_products} returned product(s) removed')
        if removed_bills > 0:
            parts.append(f'{removed_bills} bill(s) cancelled due to returns')
        if parts:
            msg += f' ({", ".join(parts)})'

        return jsonify({
            'success': True,
            'invoice_count': len(current_invoices),
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
        starting_bill_number = request.args.get('starting_bill_number', 2600001, type=int)
        invoice.bill_number = str(starting_bill_number)
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

        starting_bill_number = request.json.get('starting_bill_number', 2600001)
        matching_invoice.bill_number = str(starting_bill_number)

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
        starting_bill_number = data.get('starting_bill_number', 2600001)

        # Initialize PDF generator
        output_dir = app.config['OUTPUT_FOLDER']
        generator = PDFGenerator(output_dir)
        company = get_company_info()

        # Clean up old batch PDFs before generating new one
        for old_file in os.listdir(output_dir):
            if old_file.startswith('all_bills_') and old_file.endswith('.pdf'):
                os.remove(os.path.join(output_dir, old_file))

        # Generate all PDFs with paper settings and bill numbering
        output_files = generator.generate_batch_bills(current_invoices, company, paper_size, orientation, starting_bill_number)

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
        starting_bill_number = data.get('starting_bill_number', 2600001)
        
        # Initialize PDF generator
        output_dir = app.config['OUTPUT_FOLDER']
        generator = PDFGenerator(output_dir)
        company = get_company_info()
        
        # Assign bill number to first invoice
        current_invoices[0].bill_number = str(starting_bill_number)
        
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
        starting_bill_number = data.get('starting_bill_number', 2600001)
        
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
        
        # Assign bill number to this invoice
        matching_invoice.bill_number = str(starting_bill_number)
        
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


@app.route('/sales-report', methods=['POST'])
def sales_report():
    """Generate sales report PDF from trimmed data"""
    global current_trimmed_df

    if current_trimmed_df is None or current_trimmed_df.empty:
        return jsonify({'error': 'No data available. Please upload and process a CSV first.'}), 400

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        # Register Thai font
        try:
            pdfmetrics.registerFont(TTFont('ThaiFont', '/System/Library/Fonts/Supplemental/Tahoma.ttf'))
            pdfmetrics.registerFont(TTFont('ThaiFont-Bold', '/System/Library/Fonts/Supplemental/Tahoma Bold.ttf'))
            thai_font = 'ThaiFont'
            thai_font_bold = 'ThaiFont-Bold'
        except Exception:
            thai_font = 'Helvetica'
            thai_font_bold = 'Helvetica-Bold'

        data = request.get_json() or {}
        starting_bill_number = data.get('starting_bill_number', 2600001)

        mapping = config.get('column_mapping', CSVParser.COLUMN_MAP)
        df = current_trimmed_df.copy()

        # Column references
        order_col = mapping.get('order_id', 'หมายเลขคำสั่งซื้อ')
        product_col = mapping.get('product_name', 'ชื่อสินค้า')
        sale_price_col = mapping.get('sale_price', 'ราคาขาย')
        qty_col = mapping.get('quantity', 'จำนวน')
        shipping_buyer_col = mapping.get('shipping_buyer', 'ค่าจัดส่งที่ชำระโดยผู้ซื้อ')
        service_fee_col = mapping.get('service_fee', 'ค่าบริการ')
        grand_total_col = mapping.get('grand_total', 'จำนวนเงินทั้งหมด')
        estimated_shipping_col = mapping.get('estimated_shipping', 'ค่าจัดส่งโดยประมาณ')

        # Extract Model from product name: look for "รุ่น XXXX"
        def extract_model(product_name):
            if pd.isna(product_name):
                return ''
            match = re.search(r'รุ่น\s+(\S+)', str(product_name))
            return match.group(1) if match else ''

        # Clean numeric helper
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

        # Build report rows
        report_rows = []
        seen_orders = set()
        order_index = 0  # Running number per order (for bill number)
        # Track per-order sums for summary (invoice-level fields counted once per order)
        order_shipping_buyer = {}
        order_service_fee = {}
        order_grand_total = {}
        order_estimated_shipping = {}
        total_qty = 0.0
        row_number = 0  # Running row number
        # Track per-model stats for top 10 table
        model_stats = {}  # model -> {'total_value': float, 'total_qty': float, 'prices': []}

        # Build invoice VAT lookup from current_invoices (keyed by order_id)
        invoice_vat_lookup = {}
        for inv in current_invoices:
            invoice_vat_lookup[inv.order_id] = {
                'vat_amount': inv.vat_amount,
                'total_before_vat': inv.total_before_vat
            }

        for _, row in df.iterrows():
            oid = str(row[order_col]) if pd.notna(row[order_col]) else ''
            model = extract_model(row.get(product_col, ''))
            sale_price = clean_num(row.get(sale_price_col, 0))
            qty = clean_num(row.get(qty_col, 0))
            total_qty += qty
            row_number += 1

            # Track model stats
            if model:
                if model not in model_stats:
                    model_stats[model] = {'total_value': 0.0, 'total_qty': 0.0, 'prices': []}
                model_stats[model]['total_value'] += sale_price * qty
                model_stats[model]['total_qty'] += qty
                model_stats[model]['prices'].append(sale_price)

            is_first_row = oid not in seen_orders
            if is_first_row:
                seen_orders.add(oid)
                order_index += 1
                bill_num = str(starting_bill_number + order_index - 1)
                sb = clean_num(row.get(shipping_buyer_col, 0))
                sf = clean_num(row.get(service_fee_col, 0))
                gt = clean_num(row.get(grand_total_col, 0))
                es = clean_num(row.get(estimated_shipping_col, 0))
                vat_info = invoice_vat_lookup.get(oid, {})
                vat_amt = vat_info.get('vat_amount', 0.0)
                before_vat = vat_info.get('total_before_vat', 0.0)
                order_shipping_buyer[oid] = sb
                order_service_fee[oid] = sf
                order_grand_total[oid] = gt
                order_estimated_shipping[oid] = es
            else:
                bill_num = ''
                sb = sf = gt = es = vat_amt = before_vat = None

            report_rows.append({
                'row_num': row_number,
                'bill_number': bill_num,
                'order_id': oid if is_first_row else '',
                'model': model,
                'sale_price': sale_price,
                'qty': qty,
                'shipping_buyer': sb,
                'service_fee': sf,
                'grand_total': gt,
                'vat_amount': vat_amt,
                'total_before_vat': before_vat,
                'estimated_shipping': es,
            })

        # Build PDF
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=14, rightMargin=14, topMargin=40, bottomMargin=30)

        title_style = ParagraphStyle('Title', fontName=thai_font_bold, fontSize=14, leading=18, alignment=0)
        header_style = ParagraphStyle('Header', fontName=thai_font_bold, fontSize=7, leading=9, alignment=1)
        cell_style = ParagraphStyle('Cell', fontName=thai_font, fontSize=7, leading=9)
        cell_center = ParagraphStyle('CellCenter', fontName=thai_font, fontSize=7, leading=9, alignment=1)
        cell_right = ParagraphStyle('CellRight', fontName=thai_font, fontSize=7, leading=9, alignment=2)

        elements = []
        elements.append(Paragraph('Sales Report (รายงานยอดขาย)', title_style))
        elements.append(Spacer(1, 12))

        # Table header — 12 columns
        headers = [
            Paragraph('เลขที่บิล', header_style),
            Paragraph('หมายเลข\nคำสั่งซื้อ', header_style),
            Paragraph('Model', header_style),
            Paragraph('ราคาขาย', header_style),
            Paragraph('จำนวน', header_style),
            Paragraph('ค่าจัดส่ง\n(ผู้ซื้อ)', header_style),
            Paragraph('ค่าบริการ', header_style),
            Paragraph('ค่าจัดส่ง\nโดยประมาณ', header_style),
            Paragraph('จำนวนเงิน\nทั้งหมด', header_style),
            Paragraph('VAT 7%', header_style),
            Paragraph('ราคาก่อน\nVAT', header_style),
        ]

        def fmt(val):
            if val is None:
                return ''
            return f'{val:,.2f}'

        table_data = [headers]
        for r in report_rows:
            table_data.append([
                Paragraph(r['bill_number'], cell_center),
                Paragraph(r['order_id'], cell_style),
                Paragraph(r['model'], cell_style),
                Paragraph(fmt(r['sale_price']), cell_right),
                Paragraph(str(int(r['qty'])) if r['qty'] == int(r['qty']) else fmt(r['qty']), cell_right),
                Paragraph(fmt(r['shipping_buyer']), cell_right),
                Paragraph(fmt(r['service_fee']), cell_right),
                Paragraph(fmt(r['estimated_shipping']), cell_right),
                Paragraph(fmt(r['grand_total']), cell_right),
                Paragraph(fmt(r['vat_amount']), cell_right),
                Paragraph(fmt(r['total_before_vat']), cell_right),
            ])

        # bill, order_id, model, price, qty, shipping, fee, est_ship, total, vat, before_vat
        col_widths = [48, 80, 45, 42, 24, 46, 42, 46, 52, 42, 52]
        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), thai_font),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a90d9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f4f8')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
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

        # Sum VAT from pre-computed invoice values
        sum_vat = sum(inv.vat_amount for inv in current_invoices)
        sum_before_vat = sum(inv.total_before_vat for inv in current_invoices)

        summary_data = [
            [Paragraph('รายการ', header_style), Paragraph('ยอดรวม', header_style)],
            [Paragraph('จำนวนคำสั่งซื้อ', cell_style), Paragraph(f'{len(seen_orders):,}', cell_right)],
            [Paragraph('จำนวนสินค้า (ชิ้น)', cell_style), Paragraph(f'{int(total_qty):,}', cell_right)],
            [Paragraph('ค่าจัดส่งที่ชำระโดยผู้ซื้อ', cell_style), Paragraph(fmt(sum_shipping_buyer), cell_right)],
            [Paragraph('ค่าบริการ', cell_style), Paragraph(fmt(sum_service_fee), cell_right)],
            [Paragraph('จำนวนเงินทั้งหมด', cell_style), Paragraph(fmt(sum_grand_total), cell_right)],
            [Paragraph('ราคาก่อนภาษีมูลค่าเพิ่ม', cell_style), Paragraph(fmt(sum_before_vat), cell_right)],
            [Paragraph('ภาษีมูลค่าเพิ่ม 7%', cell_style), Paragraph(fmt(sum_vat), cell_right)],
            [Paragraph('ค่าจัดส่งโดยประมาณ', cell_style), Paragraph(fmt(sum_estimated_shipping), cell_right)],
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
