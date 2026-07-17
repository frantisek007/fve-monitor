import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    
    # Kľúčová zmena: Použi DATABASE_URL z prostredia, ak existuje
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        # Render poskytuje DATABASE_URL, ktorá už obsahuje všetky údaje
        SQLALCHEMY_DATABASE_URI = database_url
    else:
        # Lokálne použi SQLite
        instance_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
        if not os.path.exists(instance_path):
            os.makedirs(instance_path)
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{os.path.join(instance_path, "fve.db")}'
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY') or 'dev-encryption-key'