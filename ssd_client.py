import logging
import requests
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class SSDIMSClient:
    def __init__(self, username=None, password=None):
        self.username = username or os.getenv("SSD_USERNAME")
        self.password = password or os.getenv("SSD_PASSWORD")
        self.session = requests.Session()
        self.base_url = "https://ims.ssd.sk"
        self.logged_in = False
        self.delivery_points = None
        self.delivery_points_mapped = None

    def login(self):
        if self.logged_in:
            return True
        
        if not self.username or not self.password:
            logger.error("❌ Chýbajú prihlasovacie údaje k SSD")
            return False
            
        url = f"{self.base_url}/api/account/login"
        payload = {"username": self.username, "password": self.password, "rememberMe": True}
        try:
            resp = self.session.post(url, json=payload, timeout=30)  # Zvýšené na 30s
            if resp.status_code == 200:
                self.logged_in = True
                print(f"✅ Prihlásený na SSD ako {self.username}")
                return True
            else:
                print(f"❌ Prihlásenie zlyhalo: {resp.status_code}")
                return False
        except Exception as e:
            print(f"❌ Chyba pri prihlasovaní: {e}")
            return False

    def get_delivery_points(self):
        """Dynamicky stiahne zoznam odberných miest z SSD"""
        if not self.logged_in and not self.login():
            return []
        
        url = f"{self.base_url}/api/consumption-production/profile-data/get-points-of-delivery"
        try:
            print("🔍 Načítavam zoznam odberných miest z SSD...")
            resp = self.session.get(url, timeout=30)  # Zvýšené na 30s
            print(f"📡 Odpoveď: {resp.status_code}")
            
            if resp.status_code == 200:
                data = resp.json()
                self.delivery_points = data
                print(f"✅ Načítaných {len(data)} odberných miest")
                return data
            else:
                print(f"❌ Nepodarilo sa načítať odberné miesta (Kód: {resp.status_code})")
                print(f"   Odpoveď: {resp.text[:200]}")
                return []
        except Exception as e:
            print(f"❌ Chyba pri načítavaní odberných miest: {e}")
            return []

    def get_delivery_points_mapped(self):
        """Vráti zoznam odberných miest v prehľadnom formáte"""
        if self.delivery_points_mapped:
            return self.delivery_points_mapped
            
        points = self.get_delivery_points()
        if not points:
            return []
        
        mapped = []
        for idx, pt in enumerate(points, start=1):
            dp_id = pt.get("value")
            dp_text = pt.get("text", "Neznáme miesto")
            eic = dp_text.split()[0] if dp_text else f"UNKNOWN_{idx}"
            
            mapped.append({
                'id': dp_id,
                'text': dp_text,
                'eic': eic,
                'index': str(idx),
                'alias': f"P{idx}"
            })
            print(f"  P{idx}: {eic} - {dp_text[:50]}...")
        
        self.delivery_points_mapped = mapped
        return mapped

    def get_data(self, from_date, to_date, dp_id, dp_text):
        """Stiahne dáta pre konkrétne odberné miesto"""
        if not self.logged_in and not self.login():
            return None
            
        payload = {
            "pointOfDeliveryId": dp_id,
            "validFromDate": from_date,
            "validToDate": to_date,
            "pointOfDeliveryText": dp_text
        }
        
        url = f"{self.base_url}/api/consumption-production/profile-data/chart-data"
        
        try:
            print(f"📡 Sťahujem dáta pre obdobie: {from_date} - {to_date}")
            resp = self.session.post(url, json=payload, timeout=45)  # Zvýšené na 45s
            print(f"📡 Odpoveď: {resp.status_code}")
            
            if resp.status_code == 200:
                data = resp.json()
                consumption = data.get('sumActualConsumption', 0)
                production = data.get('sumActualSupply', 0)
                print(f"📊 SSD RAW: sumActualConsumption={consumption:.3f}, sumActualSupply={production:.3f}")
                return {
                    'consumption': consumption,
                    'production': production,
                    'raw_data': data
                }
            else:
                print(f"❌ Chyba: {resp.status_code} - {resp.text[:200]}")
                return None
        except requests.exceptions.Timeout:
            print(f"❌ Timeout pri sťahovaní dát (45s). Skúste neskôr.")
            return None
        except Exception as e:
            print(f"❌ Chyba pri získavaní dát: {e}")
            return None