"""Company info / company-profile routes (config.json + optional DB persistence)."""
from flask import Blueprint, request, jsonify, current_app

import app as app_module
from src.web.config_store import config, save_config
from src.web.helpers import login_required

# NOTE: DB availability and the get_all_profiles/get_profile/save_profile/
# delete_profile functions are looked up dynamically as app_module.<name>
# because they are only conditionally imported/bound onto the app module at
# startup (see app.py's DB init block) — exactly mirroring the pre-refactor
# behavior where these routes lived in app.py itself.

profiles_bp = Blueprint('profiles', __name__)


@profiles_bp.route('/save-company', methods=['POST'])
@login_required
def save_company():
    """Save company info to config and optionally to DB as a profile"""
    try:
        data = request.get_json()
        profile_name = data.get('profile_name', '').strip()
        name = data.get('name', config['company']['name'])
        tax_id = data.get('tax_id', config['company']['tax_id'])
        address = data.get('address', config['company']['address'])
        phone = data.get('phone', config['company']['phone'])

        # Always update in-memory config (used by get_company_info() for bill generation).
        config['company']['name'] = name
        config['company']['tax_id'] = tax_id
        config['company']['address'] = address
        config['company']['phone'] = phone

        use_db = app_module._db_available() and bool(profile_name)

        # config.json is a local-fallback persistence mechanism; on Render the
        # filesystem is ephemeral anyway, so this write was illusory
        # persistence there. Only write it when we're NOT persisting to the
        # DB instead (no DB configured, or no profile_name given).
        if not use_db:
            save_config()

        # Save to DB if available
        if use_db:
            try:
                app_module.save_profile(profile_name, name, tax_id, address, phone)
            except Exception:
                current_app.logger.exception('Error saving company profile to DB')
                # DB write failed — fall back to config.json so the data isn't lost.
                save_config()
                return jsonify({'success': True, 'message': 'Saved locally (DB error, see server logs).', 'profile_name': profile_name})

        return jsonify({'success': True, 'message': 'Company info saved.', 'profile_name': profile_name})
    except Exception:
        current_app.logger.exception('Error saving company info')
        return jsonify({'error': 'Internal error while saving company info. Check server logs.'}), 500


@profiles_bp.route('/api/company-profiles')
@login_required
def list_company_profiles():
    """List all saved company profiles"""
    if app_module._db_available():
        try:
            profiles = app_module.get_all_profiles()
            return jsonify({'profiles': profiles, 'source': 'db'})
        except Exception:
            pass
    # Fallback: config.json as single "Local" profile
    return jsonify({'profiles': [{'profile_name': 'Local', 'id': None}], 'source': 'config'})


@profiles_bp.route('/api/company-profiles/select/<profile_name>', methods=['POST'])
@login_required
def select_company_profile(profile_name):
    """Set active company profile — updates in-memory config for bill generation.

    NOTE (multi-worker caveat): config['company'] is process-global in-memory
    state, shared by every session on this worker — selecting a profile here
    is not per-user/per-session. That is today's semantic and is unchanged by
    this refactor; only the config.json write was removed (see below).
    """
    if app_module._db_available():
        try:
            profile = app_module.get_profile(profile_name)
            if profile:
                # DB is the source of truth here — update in-memory config only.
                # No config.json write: on Render the filesystem is ephemeral,
                # so that write was illusory persistence anyway, and the DB
                # profile is reloaded via get_profile() next time regardless.
                config['company']['name'] = profile['name']
                config['company']['tax_id'] = profile.get('tax_id', '')
                config['company']['address'] = profile.get('address', '')
                config['company']['phone'] = profile.get('phone', '')

                return jsonify({
                    'success': True,
                    'name': profile['name'],
                    'tax_id': profile.get('tax_id', ''),
                    'address': profile.get('address', ''),
                    'phone': profile.get('phone', '')
                })
        except Exception:
            current_app.logger.exception('Error selecting company profile')
            return jsonify({'error': 'Internal error while selecting company profile. Check server logs.'}), 500

    # Fallback: return current config
    if profile_name == 'Local':
        c = config['company']
        return jsonify({'success': True, 'name': c['name'], 'tax_id': c['tax_id'], 'address': c['address'], 'phone': c['phone']})

    return jsonify({'error': 'Profile not found'}), 404


@profiles_bp.route('/api/company-profiles/<profile_name>', methods=['DELETE'])
@login_required
def delete_company_profile(profile_name):
    """Delete a company profile"""
    if not app_module._db_available():
        return jsonify({'error': 'Cannot delete without database'}), 400
    try:
        success = app_module.delete_profile(profile_name)
        if success:
            return jsonify({'success': True})
        return jsonify({'error': 'Profile not found'}), 404
    except Exception:
        current_app.logger.exception('Error deleting company profile')
        return jsonify({'error': 'Internal error while deleting company profile. Check server logs.'}), 500
