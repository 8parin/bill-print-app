"""Login / logout and the main page.

Deviation from the suggested layout: the '/' index route lives here (not
split into its own module) because it shares login_required's url_for('login')
redirect target and login()'s url_for('index') redirect target. Keeping all
three in one blueprint means only two url_for() call sites (both here, plus
the one in helpers.py) needed updating to the blueprint-qualified endpoint
names ('auth.login' / 'auth.index') — no other file references these
endpoints by name (templates only use url_for('static', ...)).
"""
from flask import Blueprint, render_template, request, redirect, url_for, session

from src.web.config_store import config
from src.web.helpers import login_required, APP_PASSWORD

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == APP_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('auth.index'))
        error = 'Incorrect password'
    return render_template('login.html', error=error)


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


@auth_bp.route('/')
@login_required
def index():
    """Main page"""
    return render_template('index.html', company=config['company'])
