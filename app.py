from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import json
import logging
import os

from config import Config
from models import db, User, EnergyHistory
from crypto_utils import CryptoUtils
from ssd_client import SSDIMSClient

# Vytvorenie instance folderu
instance_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
if not os.path.exists(instance_path):
    os.makedirs(instance_path)

app = Flask(__name__, instance_path=instance_path)
app.config.from_object(Config)

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

crypto = CryptoUtils(app.config['ENCRYPTION_KEY'])

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def inject_now():
    return {
        'now': datetime.now(),
        'timedelta': timedelta
    }

# ----- ROUTY -----

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            if user.ssd_username and user.ssd_password:
                session['ssd_username'] = crypto.decrypt(user.ssd_username)
                session['ssd_password'] = crypto.decrypt(user.ssd_password)
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Nesprávne údaje', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        ssd_user = request.form.get('ssd_username')
        ssd_pass = request.form.get('ssd_password')
        battery_capacity = int(request.form.get('battery_capacity', 3))
        
        # SPRÁVNE NAČÍTANIE BILLING_DATE S KONTROLOU
        billing_date_str = request.form.get('billing_date')
        if billing_date_str:
            try:
                billing_date = datetime.strptime(billing_date_str, '%Y-%m-%d').date()
            except ValueError:
                billing_date = datetime(2026, 1, 1).date()
        else:
            billing_date = datetime(2026, 1, 1).date()
        
        # POISTKA: Ak by náhodou bolo None, nastavíme predvolenú hodnotu
        if billing_date is None:
            billing_date = datetime(2026, 1, 1).date()
        
        if User.query.filter_by(username=username).first():
            flash('Meno existuje', 'danger')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email existuje', 'danger')
            return render_template('register.html')
        
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            battery_capacity=battery_capacity,
            billing_date=billing_date
        )
        if ssd_user and ssd_pass:
            user.ssd_username = crypto.encrypt(ssd_user)
            user.ssd_password = crypto.encrypt(ssd_pass)
        
        db.session.add(user)
        db.session.commit()
        flash('Registracia uspesna!', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    billing_date = current_user.billing_date
    if not billing_date:
        billing_date = datetime(2026, 1, 1).date()
    return render_template('dashboard.html', 
                         user=current_user,
                         battery_capacity=current_user.battery_capacity,
                         billing_date=billing_date)

# ----- API -----

@app.route('/api/delivery-points')
@login_required
def get_delivery_points():
    """Získa zoznam odberných miest dynamicky z SSD"""
    try:
        ssd_username = session.get('ssd_username')
        ssd_password = session.get('ssd_password')
        
        if not ssd_username or not ssd_password:
            if current_user.ssd_username and current_user.ssd_password:
                ssd_username = crypto.decrypt(current_user.ssd_username)
                ssd_password = crypto.decrypt(current_user.ssd_password)
                session['ssd_username'] = ssd_username
                session['ssd_password'] = ssd_password
        
        if not ssd_username or not ssd_password:
            return jsonify({'error': 'Chybaju SSD udaje'}), 400
        
        client = SSDIMSClient(ssd_username, ssd_password)
        points = client.get_delivery_points_mapped()
        
        if not points:
            return jsonify({'error': 'Nepodarilo sa nacitat odberne miesta'}), 404
        
        return jsonify(points)
        
    except Exception as e:
        import traceback
        print(f"❌ Chyba: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/auto-load')
@login_required
def auto_load():
    """Automatické načítanie dát po prihlásení"""
    try:
        from datetime import datetime, timedelta
        
        billing_date = current_user.billing_date
        if not billing_date:
            billing_date = datetime(2026, 1, 1).date()
        
        end_date = datetime.now().date() - timedelta(days=1)
        
        ssd_username = session.get('ssd_username')
        ssd_password = session.get('ssd_password')
        
        if not ssd_username or not ssd_password:
            if current_user.ssd_username and current_user.ssd_password:
                ssd_username = crypto.decrypt(current_user.ssd_username)
                ssd_password = crypto.decrypt(current_user.ssd_password)
                session['ssd_username'] = ssd_username
                session['ssd_password'] = ssd_password
        
        if not ssd_username or not ssd_password:
            return jsonify({
                'success': False, 
                'error': 'Chybaju SSD udaje',
                'billing_date': billing_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d')
            })
        
        client = SSDIMSClient(ssd_username, ssd_password)
        points = client.get_delivery_points_mapped()
        
        if not points:
            return jsonify({
                'success': False, 
                'error': 'Nepodarilo sa nacitat odberne miesta',
                'billing_date': billing_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d')
            })
        
        first_point = points[0]
        point_alias = first_point['alias']
        point_id = first_point['id']
        point_text = first_point['text']
        
        from_dt = datetime.combine(billing_date, datetime.min.time())
        to_dt = datetime.combine(end_date, datetime.min.time())
        
        from_iso = from_dt.strftime("%Y-%m-%dT00:00:00+02:00")
        to_iso = to_dt.replace(hour=22, minute=0, second=0).strftime("%Y-%m-%dT22:00:00.000Z")
        
        result = client.get_data(from_iso, to_iso, point_id, point_text)
        
        if not result:
            return jsonify({
                'success': False, 
                'error': 'Nepodarilo sa ziskat data',
                'billing_date': billing_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d')
            })
        
        consumption = result.get('consumption', 0)
        production = result.get('production', 0)
        
        existing = EnergyHistory.query.filter_by(
            user_id=current_user.id,
            point_alias=point_alias
        ).all()
        
        for record in existing:
            db.session.delete(record)
        db.session.commit()
        
        history = EnergyHistory(
            user_id=current_user.id,
            date=billing_date,
            production=production,
            consumption=consumption,
            grid_import=consumption,
            grid_export=production,
            point_alias=point_alias,
            raw_data=json.dumps(result.get('raw_data', {}))
        )
        db.session.add(history)
        db.session.commit()
        
        print(f"📊 Auto-load: Spotreba={consumption:.3f} kWh, Vyroba={production:.3f} kWh")
        
        return jsonify({
            'success': True,
            'consumption': consumption,
            'production': production,
            'billing_date': billing_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'point_alias': point_alias,
            'message': f'Data automaticky nacitane: Spotreba={consumption:.3f} kWh, Vyroba={production:.3f} kWh'
        })
    except Exception as e:
        import traceback
        print(f"❌ Auto-load chyba: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
        

@app.route('/api/sync-data', methods=['POST'])
@login_required
def sync_data():
    try:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        point_alias = data.get('point_alias', 'P1')
        
        ssd_username = session.get('ssd_username')
        ssd_password = session.get('ssd_password')
        
        if not ssd_username or not ssd_password:
            if current_user.ssd_username and current_user.ssd_password:
                ssd_username = crypto.decrypt(current_user.ssd_username)
                ssd_password = crypto.decrypt(current_user.ssd_password)
                session['ssd_username'] = ssd_username
                session['ssd_password'] = ssd_password
        
        if not ssd_username or not ssd_password:
            return jsonify({'error': 'Chybaju SSD udaje'}), 400
        
        client = SSDIMSClient(ssd_username, ssd_password)
        points = client.get_delivery_points_mapped()
        
        selected_point = None
        for pt in points:
            if pt['alias'] == point_alias:
                selected_point = pt
                break
        
        if not selected_point and points:
            selected_point = points[0]
        
        if not selected_point:
            return jsonify({'error': 'Nepodarilo sa najst odberne miesto'}), 400
        
        from_dt = datetime.strptime(start_date, '%Y-%m-%d')
        to_dt = datetime.strptime(end_date, '%Y-%m-%d')
        from_iso = from_dt.strftime("%Y-%m-%dT00:00:00+02:00")
        to_iso = to_dt.replace(hour=22, minute=0, second=0).strftime("%Y-%m-%dT22:00:00.000Z")
        
        result = client.get_data(from_iso, to_iso, selected_point['id'], selected_point['text'])
        
        if not result:
            return jsonify({'error': 'Nepodarilo sa ziskat data'}), 500
        
        consumption = result.get('consumption', 0)
        production = result.get('production', 0)
        
        existing = EnergyHistory.query.filter_by(
            user_id=current_user.id,
            point_alias=point_alias
        ).all()
        
        for record in existing:
            db.session.delete(record)
        db.session.commit()
        
        history = EnergyHistory(
            user_id=current_user.id,
            date=from_dt.date(),
            production=production,
            consumption=consumption,
            grid_import=consumption,
            grid_export=production,
            point_alias=point_alias,
            raw_data=json.dumps(result.get('raw_data', {}))
        )
        db.session.add(history)
        db.session.commit()
        
        print(f"📊 Ulozeny zaznam pre OM={point_alias}: Spotreba={consumption:.3f} kWh, Vyroba={production:.3f} kWh")
        
        return jsonify({
            'success': True,
            'consumption': consumption,
            'production': production,
            'point_alias': point_alias,
            'message': f'Data nacitane: Spotreba={consumption:.3f} kWh, Vyroba={production:.3f} kWh'
        })
    except Exception as e:
        import traceback
        print(f"❌ Chyba: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
        

@app.route('/api/battery-status')
@login_required
def get_battery_status():
    try:
        point_alias = request.args.get('point_alias', 'P1')
        
        latest = EnergyHistory.query.filter_by(
            user_id=current_user.id,
            point_alias=point_alias
        ).order_by(EnergyHistory.date.desc()).first()
        
        battery_capacity_kwh = (current_user.battery_capacity or 3) * 1000
        
        if not latest:
            return jsonify({
                'current_percent': 0,
                'current_kwh': 0,
                'battery_capacity_kwh': battery_capacity_kwh,
                'total_production': 0,
                'grid_import': 0,
                'net_balance': 0,
                'last_update': 'Ziadne data',
                'point_alias': point_alias
            })
        
        production = latest.production
        grid_import = latest.consumption
        net_balance = battery_capacity_kwh - production
        
        if battery_capacity_kwh > 0:
            current_percent = min(100, max(0, (production / battery_capacity_kwh) * 100))
        else:
            current_percent = 0
        
        return jsonify({
            'current_percent': round(current_percent, 1),
            'current_kwh': round(production, 1),
            'battery_capacity_kwh': battery_capacity_kwh,
            'total_production': round(production, 1),
            'grid_import': round(grid_import, 1),
            'net_balance': round(net_balance, 1),
            'last_update': latest.date.strftime('%d.%m.%Y') if latest.date else '--',
            'point_alias': point_alias
        })
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"❌ Chyba: {str(e)}")
        print(error_detail)
        return jsonify({'error': str(e), 'detail': error_detail}), 500



# Funkcia na inicializáciu databázy (pridaj ju niekde pred spustením)
def init_db():
    with app.app_context():
        print("🔄 Inicializujem databázu...")
        print(f"📌 Používam DATABASE_URL: {app.config['SQLALCHEMY_DATABASE_URI'][:30]}...") # Zobrazí začiatok URL
        try:
            db.create_all()
            print("✅ Tabuľky boli úspešne vytvorené (alebo už existujú).")
        except Exception as e:
            print(f"❌ Chyba pri vytváraní tabuliek: {e}")

if __name__ == '__main__':
    # Zavolaj inicializáciu hneď na začiatku
    init_db()
    
    # Spustenie aplikácie
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    app.run(debug=debug_mode, host='0.0.0.0', port=port)