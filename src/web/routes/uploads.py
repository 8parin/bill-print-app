"""CSV upload, platform selection, and column-mapping routes."""
import os

from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename

import app as app_module
from src.csv_parser import CSVParser
from src.platform_presets import PLATFORM_PRESETS, detect_platform
from src.pipeline import process_csv
from src.web.config_store import config, save_config
from src.web.helpers import (
    login_required, get_state, save_state, get_sid, _get_platform_preset,
)

# NOTE: _make_parser() is looked up dynamically as app_module._make_parser(...)
# (rather than imported by name) so tests/test_app.py's
# `monkeypatch.setattr(app_module, '_make_parser', ...)` continues to affect
# these routes exactly as it did when they lived directly in app.py.

uploads_bp = Blueprint('uploads', __name__)


@uploads_bp.route('/upload', methods=['POST'])
@login_required
def upload_csv():
    """Handle CSV upload"""
    state = get_state()
    sid = get_sid()

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'File must be CSV'}), 400

    try:
        # Save file under a per-session upload subdir so concurrent users'
        # uploads (even with the same filename) never collide.
        filename = secure_filename(file.filename)
        sid_upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], sid)
        os.makedirs(sid_upload_dir, exist_ok=True)
        filepath = os.path.join(sid_upload_dir, filename)
        file.save(filepath)
        state.csv_path = filepath

        # Get platform from form data (user's dropdown selection)
        selected_platform = request.form.get('platform', '').strip() or None
        state.platform = selected_platform

        # Create parser with selected platform preset
        preset = _get_platform_preset(state.platform)
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
            'selected_platform': state.platform,
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

        save_state(state)
        return jsonify(response_data)

    except Exception:
        current_app.logger.exception('Error handling CSV upload')
        return jsonify({'error': 'Internal error while uploading the CSV. Check server logs.'}), 500


@uploads_bp.route('/get-field-definitions')
@login_required
def get_field_definitions():
    """Get field definitions for mapping UI"""
    state = get_state()
    parser = app_module._make_parser(state.platform)
    return jsonify({
        'fields': parser.get_field_definitions(),
        'required_fields': parser.REQUIRED_FIELDS,
        'current_mapping': parser.column_map,
        'platform': state.platform
    })


@uploads_bp.route('/set-platform', methods=['POST'])
@login_required
def set_platform():
    """Set the active platform (called when user changes dropdown)"""
    state = get_state()
    data = request.get_json() or {}
    state.platform = data.get('platform') or None
    save_state(state)
    preset = _get_platform_preset(state.platform)
    return jsonify({
        'success': True,
        'platform': state.platform,
        'platform_name': preset.display_name if preset else 'Unknown'
    })


@uploads_bp.route('/save-mapping', methods=['POST'])
@login_required
def save_mapping():
    """Save custom column mapping"""
    state = get_state()

    try:
        mapping = request.json.get('mapping', {})

        # Validate mapping
        parser = app_module._make_parser(state.platform)
        valid, errors = parser.validate_mapping(mapping)

        if not valid:
            return jsonify({'error': 'Invalid mapping', 'details': errors}), 400

        # Save to config
        config['column_mapping'] = mapping
        save_config()

        csv_path = state.csv_path
        if not csv_path:
            return jsonify({
                'success': True,
                'message': 'Mapping saved to config. Please upload a CSV file first.'
            })

        parser_with_mapping = app_module._make_parser(state.platform, custom_column_map=mapping)
        result = process_csv(parser_with_mapping, csv_path)

        if result.needs_return_review:
            msg = 'Mapping saved! Found return/refund items that need review.'
            parts = []
            if result.cancelled_count > 0:
                parts.append(f'{result.cancelled_count} cancelled invoice(s) filtered out')
            if result.preorder_count > 0:
                parts.append(f'{result.preorder_count} pre-order row(s) filtered out')
            if result.auto_return_count > 0:
                parts.append(f'{result.auto_return_count} confirmed returned item(s) auto-removed')
            if parts:
                msg += f' ({", ".join(parts)})'

            save_state(state)
            return jsonify({
                'success': True,
                'needs_return_review': True,
                'return_items': result.return_items,
                'cancelled_count': result.cancelled_count,
                'auto_return_count': result.auto_return_count,
                'message': msg
            })
        else:
            state.pending_orders = result.pending_orders
            state.trimmed_df = result.trimmed_df
            state.invoices = result.invoices
            save_state(state)

            msg = f'Mapping saved! Found {len(state.invoices)} invoices.'
            parts = []
            if result.cancelled_count > 0:
                parts.append(f'{result.cancelled_count} cancelled invoice(s) filtered out')
            if result.preorder_count > 0:
                parts.append(f'{result.preorder_count} pre-order row(s) filtered out')
            if result.auto_return_count > 0:
                parts.append(f'{result.auto_return_count} confirmed returned item(s) auto-removed')
            if parts:
                msg += f' ({", ".join(parts)})'

            return jsonify({
                'success': True,
                'invoice_count': len(state.invoices),
                'cancelled_count': result.cancelled_count,
                'auto_return_count': result.auto_return_count,
                'message': msg
            })

    except Exception:
        current_app.logger.exception('Error saving column mapping')
        return jsonify({'error': 'Internal error while saving the column mapping. Check server logs.'}), 500


@uploads_bp.route('/apply-return-decisions', methods=['POST'])
@login_required
def apply_return_decisions():
    """Apply user decisions about returned items, then parse invoices"""
    state = get_state()

    try:
        data = request.get_json() or {}
        decisions = data.get('decisions', [])

        csv_path = state.csv_path
        if not csv_path:
            return jsonify({'error': 'No CSV file loaded. Please upload a CSV first.'}), 400

        # When a platform preset is active, use it directly (ignore saved custom mapping)
        if state.platform:
            parser = app_module._make_parser(state.platform)
        else:
            mapping = config.get('column_mapping', CSVParser.COLUMN_MAP)
            parser = app_module._make_parser(state.platform, custom_column_map=mapping)

        result = process_csv(parser, csv_path, decisions=decisions)

        state.pending_orders = result.pending_orders
        state.trimmed_df = result.trimmed_df
        state.invoices = result.invoices
        save_state(state)

        # Count how many items were removed
        removed_products = sum(1 for d in decisions if d.get('action') == 'remove_product')
        removed_bills = sum(1 for d in decisions if d.get('action') == 'remove_bill')

        msg = f'Found {len(state.invoices)} invoices.'
        parts = []
        if result.cancelled_count > 0:
            parts.append(f'{result.cancelled_count} cancelled')
        if result.preorder_count > 0:
            parts.append(f'{result.preorder_count} pre-order row(s) filtered out')
        if result.auto_return_count > 0:
            parts.append(f'{result.auto_return_count} confirmed returned item(s) auto-removed')
        if removed_products > 0:
            parts.append(f'{removed_products} returned product(s) removed')
        if removed_bills > 0:
            parts.append(f'{removed_bills} bill(s) cancelled due to returns')
        if state.pending_orders:
            parts.append(f'{len(state.pending_orders)} pending (not yet shipped)')
        if parts:
            msg += f' ({", ".join(parts)})'

        return jsonify({
            'success': True,
            'invoice_count': len(state.invoices),
            'pending_count': len(state.pending_orders),
            'message': msg
        })

    except Exception:
        current_app.logger.exception('Error applying return decisions')
        return jsonify({'error': 'Internal error while applying return decisions. Check server logs.'}), 500
