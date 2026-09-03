"""Bill preview / PDF generation / download routes, plus /stats and /version."""
import os

from flask import Blueprint, request, jsonify, render_template, make_response, send_from_directory, current_app
from werkzeug.utils import secure_filename

from src.pdf_generator_reportlab import PDFGeneratorReportLab as PDFGenerator
from src.web.helpers import (
    login_required, get_state, save_state, get_sid, get_company_info,
    _assign_bill_numbers, parse_bill_number,
)

bills_bp = Blueprint('bills', __name__)


@bills_bp.route('/preview')
@login_required
def preview_bill():
    """Preview first bill as HTML"""
    state = get_state()

    if not state.invoices:
        return jsonify({'error': 'No invoices loaded'}), 400

    try:
        # Get first invoice
        invoice = state.invoices[0]
        starting_bill_str = request.args.get('starting_bill_number', '2600001')
        _bill_prefix, _bill_start = parse_bill_number(starting_bill_str)
        _assign_bill_numbers(state, _bill_prefix, _bill_start)
        save_state(state)
        company = get_company_info()

        # Return rendered template
        return render_template('bill_template.html', invoice=invoice, company=company)

    except Exception:
        current_app.logger.exception('Error rendering bill preview')
        return jsonify({'error': 'Internal error while rendering the bill preview. Check server logs.'}), 500


@bills_bp.route('/preview-by-order', methods=['POST'])
@login_required
def preview_by_order():
    """Preview specific bill by order number"""
    state = get_state()

    if not state.invoices:
        return jsonify({'error': 'No invoices loaded'}), 400

    try:
        order_number = request.json.get('order_number', '').strip()

        if not order_number:
            return jsonify({'error': 'Order number is required'}), 400

        # Find invoice with matching order number OR tax invoice number
        matching_invoice = None
        for invoice in state.invoices:
            if (str(invoice.order_id) == str(order_number) or
                str(invoice.invoice_number) == str(order_number)):
                matching_invoice = invoice
                break

        if not matching_invoice:
            return jsonify({'error': f'Order/Invoice number {order_number} not found'}), 404

        starting_bill_str = str(request.json.get('starting_bill_number', '2600001'))
        _bill_prefix, _bill_start = parse_bill_number(starting_bill_str)
        _assign_bill_numbers(state, _bill_prefix, _bill_start)
        save_state(state)

        company = get_company_info()
        html = render_template('bill_template.html', invoice=matching_invoice, company=company)

        return jsonify({
            'success': True,
            'html': html,
            'invoice_number': matching_invoice.invoice_number,
            'order_id': matching_invoice.order_id
        })

    except Exception:
        current_app.logger.exception('Error rendering bill preview by order')
        return jsonify({'error': 'Internal error while rendering the bill preview by order. Check server logs.'}), 500


@bills_bp.route('/generate', methods=['POST'])
@login_required
def generate_bills():
    """Generate all PDFs"""
    state = get_state()

    if not state.invoices:
        return jsonify({'error': 'No invoices loaded'}), 400

    try:
        sid = get_sid()

        # Get paper settings from request
        data = request.get_json() or {}
        paper_size = data.get('paper_size', 'A5')
        orientation = data.get('orientation', 'portrait')
        starting_bill_str = str(data.get('starting_bill_number', '2600001'))
        bill_prefix, bill_start_num = parse_bill_number(starting_bill_str)

        # Stamp bill numbers once — invoice.bill_number and __bill_number__ column both set here.
        # PDF generator and sales report read these values; neither re-computes.
        _assign_bill_numbers(state, bill_prefix, bill_start_num)

        # Namespace outputs per session so concurrent users never clobber each other's PDFs.
        output_dir = os.path.join(current_app.config['OUTPUT_FOLDER'], sid)
        os.makedirs(output_dir, exist_ok=True)
        generator = PDFGenerator(output_dir)
        company = get_company_info()

        # Clean up old batch PDFs (this session's own) before generating new one
        for old_file in os.listdir(output_dir):
            if old_file.startswith('all_bills_') and old_file.endswith('.pdf'):
                os.remove(os.path.join(output_dir, old_file))

        # Generate all PDFs — invoice.bill_number is already set by _assign_bill_numbers above
        # pending_orders are prepended as a summary page (page 1) if any exist
        output_files = generator.generate_batch_bills(
            state.invoices, company, paper_size, orientation,
            pending_orders=state.pending_orders
        )

        # Verify the generated files actually exist
        existing_files = [f for f in output_files if os.path.exists(f)]
        if not existing_files:
            return jsonify({'error': 'PDF generation failed - no output files created'}), 500

        save_state(state)
        return jsonify({
            'success': True,
            'count': len(existing_files),
            'files': [os.path.basename(f) for f in existing_files],
            'message': f'Successfully generated {len(existing_files)} bills ({paper_size} {orientation})'
        })

    except Exception:
        current_app.logger.exception('Error generating batch bills')
        return jsonify({'error': 'Internal error while generating bills. Check server logs.'}), 500


@bills_bp.route('/debug-bills')
@login_required
def debug_bills():
    """Return trimmed DataFrame bill assignment for debugging.

    Open http://localhost:5003/debug-bills after generating bills to inspect
    the full order → bill-number mapping as JSON.
    """
    state = get_state()
    if state.trimmed_df is None:
        return jsonify({'error': 'No data loaded. Upload and validate a CSV first.'}), 400
    cols = ['__bill_order__', '__bill_number__']
    for c in ['หมายเลขคำสั่งซื้อ', 'เวลาส่งสินค้า', 'ชื่อผู้รับ']:
        if c in state.trimmed_df.columns:
            cols.append(c)
    available = [c for c in cols if c in state.trimmed_df.columns]
    if '__bill_number__' not in available:
        return jsonify({'error': 'Bill numbers not yet assigned. Generate bills first.'}), 400
    df_debug = state.trimmed_df[available].drop_duplicates(subset=['__bill_order__']).fillna('').copy()
    return jsonify({
        'row_count': len(df_debug),
        'columns': available,
        'rows': df_debug.to_dict(orient='records')
    })


@bills_bp.route('/generate-one', methods=['POST'])
@login_required
def generate_one_bill():
    """Generate single PDF (first invoice only)"""
    state = get_state()

    if not state.invoices:
        return jsonify({'error': 'No invoices loaded'}), 400

    try:
        sid = get_sid()

        # Get paper settings from request
        data = request.get_json() or {}
        paper_size = data.get('paper_size', 'A5')
        orientation = data.get('orientation', 'portrait')
        starting_bill_str = str(data.get('starting_bill_number', '2600001'))

        # Namespace outputs per session so concurrent users never clobber each other's PDFs.
        output_dir = os.path.join(current_app.config['OUTPUT_FOLDER'], sid)
        os.makedirs(output_dir, exist_ok=True)
        generator = PDFGenerator(output_dir)
        company = get_company_info()

        # Stamp bill numbers on all invoices (and DF) so all are consistent
        _bill_prefix, _bill_start = parse_bill_number(starting_bill_str)
        _assign_bill_numbers(state, _bill_prefix, _bill_start)

        # Generate first invoice only with paper settings
        output_path = generator.generate_single_bill(state.invoices[0], company, paper_size, orientation)
        filename = os.path.basename(output_path)

        save_state(state)
        return jsonify({
            'success': True,
            'filename': filename,
            'invoice_number': state.invoices[0].invoice_number,
            'message': f'Successfully generated bill for invoice {state.invoices[0].invoice_number} ({paper_size} {orientation})'
        })

    except Exception:
        current_app.logger.exception('Error generating single bill')
        return jsonify({'error': 'Internal error while generating the bill. Check server logs.'}), 500


@bills_bp.route('/generate-by-order', methods=['POST'])
@login_required
def generate_by_order():
    """Generate PDF for specific order number or tax invoice number"""
    state = get_state()

    if not state.invoices:
        return jsonify({'error': 'No invoices loaded'}), 400

    try:
        sid = get_sid()

        data = request.get_json() or {}
        order_number = data.get('order_number', '').strip()
        paper_size = data.get('paper_size', 'A5')
        orientation = data.get('orientation', 'portrait')
        starting_bill_str = str(data.get('starting_bill_number', '2600001'))

        if not order_number:
            return jsonify({'error': 'Order number is required'}), 400

        # Find invoice with matching order number OR tax invoice number
        matching_invoice = None
        for invoice in state.invoices:
            if (str(invoice.order_id) == str(order_number) or
                str(invoice.invoice_number) == str(order_number)):
                matching_invoice = invoice
                break

        if not matching_invoice:
            return jsonify({'error': f'Order/Invoice number {order_number} not found'}), 404

        # Namespace outputs per session so concurrent users never clobber each other's PDFs.
        output_dir = os.path.join(current_app.config['OUTPUT_FOLDER'], sid)
        os.makedirs(output_dir, exist_ok=True)
        generator = PDFGenerator(output_dir)
        company = get_company_info()

        # Stamp bill numbers on all invoices (and DF) so all are consistent
        _bill_prefix, _bill_start = parse_bill_number(starting_bill_str)
        _assign_bill_numbers(state, _bill_prefix, _bill_start)

        # Generate bill with paper settings
        output_path = generator.generate_single_bill(matching_invoice, company, paper_size, orientation)
        filename = os.path.basename(output_path)

        save_state(state)
        return jsonify({
            'success': True,
            'filename': filename,
            'invoice_number': matching_invoice.invoice_number,
            'order_id': matching_invoice.order_id,
            'message': f'Successfully generated bill for order {matching_invoice.order_id} ({paper_size} {orientation})'
        })

    except Exception:
        current_app.logger.exception('Error generating bill by order')
        return jsonify({'error': 'Internal error while generating the bill. Check server logs.'}), 500


@bills_bp.route('/download/<filename>')
@login_required
def download_file(filename):
    """Download a single PDF from this session's own output subdir"""
    sid = get_sid()
    safe_name = secure_filename(filename)
    output_dir = os.path.join(current_app.config['OUTPUT_FOLDER'], sid)
    filepath = os.path.join(output_dir, safe_name)

    if not safe_name or not os.path.exists(filepath):
        return jsonify({'error': f'File not found: {filename}'}), 404

    response = make_response(send_from_directory(output_dir, safe_name, as_attachment=True))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@bills_bp.route('/download-all')
@login_required
def download_all():
    """Download the batch-generated PDF file from this session's own output subdir"""
    try:
        sid = get_sid()
        output_dir = os.path.join(current_app.config['OUTPUT_FOLDER'], sid)

        # Find the most recent all_bills PDF by modification time
        pdf_files = (
            [f for f in os.listdir(output_dir) if f.startswith('all_bills_') and f.endswith('.pdf')]
            if os.path.isdir(output_dir) else []
        )

        if not pdf_files:
            return jsonify({'error': 'No batch PDF found. Please generate bills first.'}), 404

        # Sort by modification time (newest first)
        pdf_files.sort(key=lambda f: os.path.getmtime(os.path.join(output_dir, f)), reverse=True)
        latest_pdf = pdf_files[0]

        # send_from_directory (same as /download) sets Content-Type from the
        # file extension and the attachment Content-Disposition from the
        # filename — equivalent to the old manual open()+headers version, but
        # consistent with /download instead of reading the file into memory.
        response = make_response(send_from_directory(output_dir, latest_pdf, as_attachment=True))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    except Exception:
        current_app.logger.exception('Error downloading batch PDF')
        return jsonify({'error': 'Internal error while downloading the batch PDF. Check server logs.'}), 500


@bills_bp.route('/stats')
@login_required
def get_stats():
    """Get current statistics"""
    state = get_state()

    return jsonify({
        'invoice_count': len(state.invoices),
        'output_folder': current_app.config['OUTPUT_FOLDER']
    })


@bills_bp.route('/version')
def version():
    """Deployed version marker — Render sets RENDER_GIT_COMMIT on every deploy."""
    return jsonify({
        'commit': os.environ.get('RENDER_GIT_COMMIT', 'local')[:7],
    })
