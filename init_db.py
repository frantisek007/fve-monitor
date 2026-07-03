from app import app, db
from models import User, EnergyHistory

with app.app_context():
    db.create_all()
    print('Tabulky vytvorene')
