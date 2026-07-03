from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'user'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    
    ssd_username = db.Column(db.String(200))
    ssd_password = db.Column(db.String(200))
    
    fve_capacity = db.Column(db.Float, default=5.0)
    battery_capacity = db.Column(db.Integer, default=3)
    
    # Dátum vyúčtovania VB
    billing_date = db.Column(db.Date, default=datetime.now().replace(month=1, day=1))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_sync = db.Column(db.DateTime)
    
    history = db.relationship('EnergyHistory', backref='user', lazy=True)

class EnergyHistory(db.Model):
    __tablename__ = 'energy_history'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    production = db.Column(db.Float, default=0)
    consumption = db.Column(db.Float, default=0)
    grid_import = db.Column(db.Float, default=0)
    grid_export = db.Column(db.Float, default=0)
    point_alias = db.Column(db.String(10), default='LL')
    raw_data = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)