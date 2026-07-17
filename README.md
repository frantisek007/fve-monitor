# Monitor Virtualnej Batérie (FVE Monitor)

Webová aplikácia na monitoring a optimalizáciu virtuálnej batérie pre majiteľov fotovoltických elektrární.

## 🚀 Funkcie
- Bezpečná autentifikácia s hashovaním hesiel
- Dynamické načítanie odberných miest z SSD portálu
- Prehľadný dashboard so stavom VB, uloženou energiou a nákupom zo siete
- Automatická synchronizácia dát po prihlásení
- Responzívny dizajn pre desktop aj mobil

## 🛠️ Technológie
- Python 3.14+
- Flask 3.0.3
- SQLAlchemy
- SQLite / PostgreSQL
- Bootstrap 5
- Chart.js

## 📦 Inštalácia

```bash
# 1. Klonovanie repozitára
git clone https://github.com/tvoj-ucet/fve-monitor.git
cd fve-monitor

# 2. Vytvorenie virtuálneho prostredia
python -m venv venv
source venv/bin/activate  # Linux/Mac
# alebo
venv\Scripts\activate  # Windows

# 3. Inštalácia závislostí
pip install -r requirements.txt

# 4. Vytvorenie .env súboru
cp .env.example .env
# Upravte .env s vašimi údajmi

# 5. Inicializácia databázy
python -c "from app import app, db; from models import User, EnergyHistory; with app.app_context(): db.create_all()"

# 6. Spustenie
python app.py
