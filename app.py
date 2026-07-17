from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from crypto_utils import CryptoUtils
from models import EnergyHistory, User, db
from ssd_client import SSDIMSClient


# ---------------------------------------------------------------------------
# ZÁKLADNÉ NASTAVENIA
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)

LOCAL_TIMEZONE = ZoneInfo("Europe/Bratislava")
DEFAULT_BILLING_DATE = date(2026, 1, 1)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def normalize_database_url(database_url: str) -> str:
    """
    Render poskytuje URL obvykle ako postgresql://...
    Táto aplikácia používa moderný psycopg 3 driver.
    """
    database_url = database_url.strip()

    if database_url.startswith("postgres://"):
        return database_url.replace(
            "postgres://",
            "postgresql+psycopg://",
            1,
        )

    if database_url.startswith("postgresql://"):
        return database_url.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    return database_url


def hide_database_password(database_url: str) -> str:
    """Skryje heslo pri vypisovaní databázovej URL do logu."""
    try:
        from sqlalchemy.engine import make_url

        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        return "<databázová URL je nastavená>"


def create_app() -> Flask:
    app = Flask(
        __name__,
        instance_path=str(INSTANCE_DIR),
        instance_relative_config=False,
    )

    app.config.from_object(Config)

    # DATABASE_URL z Renderu má prednosť pred hodnotou v config.py.
    render_database_url = os.getenv("DATABASE_URL")
    configured_database_url = render_database_url or app.config.get(
        "SQLALCHEMY_DATABASE_URI"
    )

    # SQLite iba ako lokálna záloha. Na Renderi nastav DATABASE_URL.
    if not configured_database_url:
        configured_database_url = f"sqlite:///{INSTANCE_DIR / 'fve_monitor.db'}"
        logger.warning(
            "DATABASE_URL nie je nastavená. Používa sa lokálna SQLite databáza."
        )

    configured_database_url = normalize_database_url(configured_database_url)

    app.config["SQLALCHEMY_DATABASE_URI"] = configured_database_url
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    app.config.setdefault(
        "SQLALCHEMY_ENGINE_OPTIONS",
        {
            "pool_pre_ping": True,
            "pool_recycle": 300,
        },
    )

    # Bezpečnejšie cookies pri HTTPS na Renderi.
    is_production = os.getenv("FLASK_ENV") == "production" or bool(
        os.getenv("RENDER")
    )
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = is_production
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "Chýba SECRET_KEY. Nastav ju v Render Environment Variables."
        )

    encryption_key = app.config.get("ENCRYPTION_KEY")
    if not encryption_key:
        raise RuntimeError(
            "Chýba ENCRYPTION_KEY. Nastav ju v Render Environment Variables."
        )

    # Render je za reverzným proxy serverom.
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_port=1,
    )

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Pre pokračovanie sa prihláste."
    login_manager.login_message_category = "warning"

    crypto = CryptoUtils(encryption_key)
    app.extensions["crypto_utils"] = crypto

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    @app.context_processor
    def inject_now() -> dict[str, Any]:
        return {
            "now": datetime.now(LOCAL_TIMEZONE),
            "timedelta": timedelta,
        }

    # -----------------------------------------------------------------------
    # POMOCNÉ FUNKCIE
    # -----------------------------------------------------------------------

    def parse_billing_date(value: str | None) -> date:
        if not value:
            return DEFAULT_BILLING_DATE

        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return DEFAULT_BILLING_DATE

    def parse_positive_int(
        value: str | None,
        default: int,
        minimum: int = 1,
        maximum: int = 1_000_000,
    ) -> int:
        try:
            parsed = int(value or default)
        except (TypeError, ValueError):
            return default

        return min(maximum, max(minimum, parsed))

    def get_crypto() -> CryptoUtils:
        return app.extensions["crypto_utils"]

    def get_ssd_credentials() -> tuple[str | None, str | None]:
        """
        Najskôr použije údaje zo session.
        Ak tam nie sú, bezpečne ich načíta z databázy.
        """
        ssd_username = session.get("ssd_username")
        ssd_password = session.get("ssd_password")

        if ssd_username and ssd_password:
            return ssd_username, ssd_password

        if not current_user.is_authenticated:
            return None, None

        if not current_user.ssd_username or not current_user.ssd_password:
            return None, None

        try:
            crypto_utils = get_crypto()
            ssd_username = crypto_utils.decrypt(current_user.ssd_username)
            ssd_password = crypto_utils.decrypt(current_user.ssd_password)
        except Exception:
            logger.exception(
                "Nepodarilo sa dešifrovať SSD údaje používateľa %s.",
                current_user.id,
            )
            return None, None

        session["ssd_username"] = ssd_username
        session["ssd_password"] = ssd_password

        return ssd_username, ssd_password

    def create_ssd_client() -> SSDIMSClient | None:
        ssd_username, ssd_password = get_ssd_credentials()

        if not ssd_username or not ssd_password:
            return None

        return SSDIMSClient(ssd_username, ssd_password)

    def make_ssd_date_range(
        start_date: date,
        end_date: date,
    ) -> tuple[str, str]:
        """
        Vytvorí interval od začiatku start_date po začiatok dňa
        nasledujúceho po end_date.

        Automaticky rešpektuje zimný a letný čas v Bratislave.
        """
        start_local = datetime.combine(
            start_date,
            time.min,
            tzinfo=LOCAL_TIMEZONE,
        )
        end_exclusive_local = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
            tzinfo=LOCAL_TIMEZONE,
        )

        from_iso = start_local.isoformat(timespec="seconds")
        to_iso = (
            end_exclusive_local.astimezone(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

        return from_iso, to_iso

    def save_energy_history(
        *,
        point_alias: str,
        record_date: date,
        result: dict[str, Any],
    ) -> tuple[float, float]:
        consumption = float(result.get("consumption") or 0)
        production = float(result.get("production") or 0)

        try:
            # Aplikácia uchováva jeden súhrnný záznam na používateľa a OM.
            EnergyHistory.query.filter_by(
                user_id=current_user.id,
                point_alias=point_alias,
            ).delete(synchronize_session=False)

            history = EnergyHistory(
                user_id=current_user.id,
                date=record_date,
                production=production,
                consumption=consumption,
                grid_import=consumption,
                grid_export=production,
                point_alias=point_alias,
                raw_data=json.dumps(
                    result.get("raw_data", {}),
                    ensure_ascii=False,
                    default=str,
                ),
            )

            db.session.add(history)
            db.session.commit()

            return consumption, production

        except Exception:
            db.session.rollback()
            raise

    # -----------------------------------------------------------------------
    # WEB ROUTY
    # -----------------------------------------------------------------------

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        return redirect(url_for("login"))

    @app.route("/health")
    def health():
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify(
                {
                    "status": "ok",
                    "database": "connected",
                    "time": datetime.now(timezone.utc).isoformat(),
                }
            )
        except SQLAlchemyError:
            logger.exception("Health check databázy zlyhal.")
            return jsonify(
                {
                    "status": "error",
                    "database": "unavailable",
                }
            ), 503

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""

            user = User.query.filter_by(username=username).first()

            if user and check_password_hash(user.password_hash, password):
                login_user(user)
                session.permanent = True

                if user.ssd_username and user.ssd_password:
                    try:
                        crypto_utils = get_crypto()
                        session["ssd_username"] = crypto_utils.decrypt(
                            user.ssd_username
                        )
                        session["ssd_password"] = crypto_utils.decrypt(
                            user.ssd_password
                        )
                    except Exception:
                        logger.exception(
                            "SSD údaje používateľa %s sa nepodarilo dešifrovať.",
                            user.id,
                        )
                        session.pop("ssd_username", None)
                        session.pop("ssd_password", None)
                        flash(
                            "Prihlásenie bolo úspešné, ale SSD údaje sa "
                            "nepodarilo načítať.",
                            "warning",
                        )

                return redirect(url_for("dashboard"))

            flash("Nesprávne používateľské meno alebo heslo.", "danger")

        return render_template("login.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            ssd_username = (request.form.get("ssd_username") or "").strip()
            ssd_password = request.form.get("ssd_password") or ""

            battery_capacity = parse_positive_int(
                request.form.get("battery_capacity"),
                default=3,
            )
            billing_date = parse_billing_date(
                request.form.get("billing_date")
            )

            if len(username) < 3:
                flash(
                    "Používateľské meno musí mať aspoň 3 znaky.",
                    "danger",
                )
                return render_template("register.html")

            if not email or "@" not in email:
                flash("Zadajte platnú e-mailovú adresu.", "danger")
                return render_template("register.html")

            if len(password) < 8:
                flash("Heslo musí mať aspoň 8 znakov.", "danger")
                return render_template("register.html")

            if bool(ssd_username) != bool(ssd_password):
                flash(
                    "Vyplňte SSD používateľské meno aj SSD heslo.",
                    "danger",
                )
                return render_template("register.html")

            if User.query.filter_by(username=username).first():
                flash("Používateľské meno už existuje.", "danger")
                return render_template("register.html")

            if User.query.filter_by(email=email).first():
                flash("E-mailová adresa už existuje.", "danger")
                return render_template("register.html")

            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                battery_capacity=battery_capacity,
                billing_date=billing_date,
            )

            if ssd_username and ssd_password:
                crypto_utils = get_crypto()
                user.ssd_username = crypto_utils.encrypt(ssd_username)
                user.ssd_password = crypto_utils.encrypt(ssd_password)

            try:
                db.session.add(user)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash(
                    "Používateľské meno alebo e-mail už existuje.",
                    "danger",
                )
                return render_template("register.html")
            except SQLAlchemyError:
                db.session.rollback()
                logger.exception("Registrácia používateľa zlyhala.")
                flash(
                    "Registráciu sa nepodarilo dokončiť. Skúste to znova.",
                    "danger",
                )
                return render_template("register.html")

            flash("Registrácia bola úspešná. Teraz sa prihláste.", "success")
            return redirect(url_for("login"))

        return render_template("register.html")

    @app.route("/logout", methods=["GET", "POST"])
    @login_required
    def logout():
        logout_user()
        session.clear()
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        billing_date = current_user.billing_date or DEFAULT_BILLING_DATE

        return render_template(
            "dashboard.html",
            user=current_user,
            battery_capacity=current_user.battery_capacity,
            billing_date=billing_date,
        )

    # -----------------------------------------------------------------------
    # API ROUTY
    # -----------------------------------------------------------------------

    @app.route("/api/delivery-points")
    @login_required
    def get_delivery_points():
        try:
            client = create_ssd_client()

            if client is None:
                return jsonify({"error": "Chýbajú SSD prihlasovacie údaje."}), 400

            points = client.get_delivery_points_mapped()

            if not points:
                return jsonify(
                    {"error": "Nepodarilo sa načítať odberné miesta."}
                ), 404

            return jsonify(points)

        except Exception as exc:
            logger.exception("Načítanie odberných miest zlyhalo.")
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/auto-load")
    @login_required
    def auto_load():
        try:
            billing_date = current_user.billing_date or DEFAULT_BILLING_DATE
            end_date = datetime.now(LOCAL_TIMEZONE).date() - timedelta(days=1)

            if end_date < billing_date:
                return jsonify(
                    {
                        "success": False,
                        "error": "Dátum vyúčtovania je neskorší než posledný "
                        "dostupný deň.",
                        "billing_date": billing_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    }
                ), 400

            client = create_ssd_client()

            if client is None:
                return jsonify(
                    {
                        "success": False,
                        "error": "Chýbajú SSD prihlasovacie údaje.",
                        "billing_date": billing_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    }
                ), 400

            points = client.get_delivery_points_mapped()

            if not points:
                return jsonify(
                    {
                        "success": False,
                        "error": "Nepodarilo sa načítať odberné miesta.",
                        "billing_date": billing_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    }
                ), 404

            first_point = points[0]
            point_alias = first_point["alias"]
            point_id = first_point["id"]
            point_text = first_point["text"]

            from_iso, to_iso = make_ssd_date_range(
                billing_date,
                end_date,
            )

            result = client.get_data(
                from_iso,
                to_iso,
                point_id,
                point_text,
            )

            if not result:
                return jsonify(
                    {
                        "success": False,
                        "error": "Nepodarilo sa získať dáta zo SSD.",
                        "billing_date": billing_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    }
                ), 502

            consumption, production = save_energy_history(
                point_alias=point_alias,
                record_date=billing_date,
                result=result,
            )

            logger.info(
                "Auto-load user=%s OM=%s spotreba=%.3f výroba=%.3f",
                current_user.id,
                point_alias,
                consumption,
                production,
            )

            return jsonify(
                {
                    "success": True,
                    "consumption": consumption,
                    "production": production,
                    "billing_date": billing_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "point_alias": point_alias,
                    "message": (
                        f"Dáta načítané: spotreba {consumption:.3f} kWh, "
                        f"výroba {production:.3f} kWh."
                    ),
                }
            )

        except Exception as exc:
            db.session.rollback()
            logger.exception("Automatické načítanie dát zlyhalo.")
            return jsonify(
                {
                    "success": False,
                    "error": str(exc),
                }
            ), 500

    @app.route("/api/sync-data", methods=["POST"])
    @login_required
    def sync_data():
        try:
            payload = request.get_json(silent=True) or {}

            start_date_string = payload.get("start_date")
            end_date_string = payload.get("end_date")
            point_alias = str(payload.get("point_alias") or "P1").strip()

            if not start_date_string or not end_date_string:
                return jsonify(
                    {"error": "Chýba start_date alebo end_date."}
                ), 400

            try:
                start_date = datetime.strptime(
                    start_date_string,
                    "%Y-%m-%d",
                ).date()
                end_date = datetime.strptime(
                    end_date_string,
                    "%Y-%m-%d",
                ).date()
            except ValueError:
                return jsonify(
                    {"error": "Dátumy musia mať formát YYYY-MM-DD."}
                ), 400

            if end_date < start_date:
                return jsonify(
                    {"error": "end_date nesmie byť pred start_date."}
                ), 400

            client = create_ssd_client()

            if client is None:
                return jsonify(
                    {"error": "Chýbajú SSD prihlasovacie údaje."}
                ), 400

            points = client.get_delivery_points_mapped() or []

            selected_point = next(
                (
                    point
                    for point in points
                    if point.get("alias") == point_alias
                ),
                None,
            )

            if selected_point is None and points:
                selected_point = points[0]
                point_alias = selected_point.get("alias", point_alias)

            if selected_point is None:
                return jsonify(
                    {"error": "Nepodarilo sa nájsť odberné miesto."}
                ), 404

            from_iso, to_iso = make_ssd_date_range(
                start_date,
                end_date,
            )

            result = client.get_data(
                from_iso,
                to_iso,
                selected_point["id"],
                selected_point["text"],
            )

            if not result:
                return jsonify(
                    {"error": "Nepodarilo sa získať dáta zo SSD."}
                ), 502

            consumption, production = save_energy_history(
                point_alias=point_alias,
                record_date=start_date,
                result=result,
            )

            logger.info(
                "Sync user=%s OM=%s spotreba=%.3f výroba=%.3f",
                current_user.id,
                point_alias,
                consumption,
                production,
            )

            return jsonify(
                {
                    "success": True,
                    "consumption": consumption,
                    "production": production,
                    "point_alias": point_alias,
                    "message": (
                        f"Dáta načítané: spotreba {consumption:.3f} kWh, "
                        f"výroba {production:.3f} kWh."
                    ),
                }
            )

        except Exception as exc:
            db.session.rollback()
            logger.exception("Ručná synchronizácia dát zlyhala.")
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/battery-status")
    @login_required
    def get_battery_status():
        try:
            point_alias = (
                request.args.get("point_alias", "P1").strip() or "P1"
            )

            latest = (
                EnergyHistory.query.filter_by(
                    user_id=current_user.id,
                    point_alias=point_alias,
                )
                .order_by(EnergyHistory.date.desc())
                .first()
            )

            # Zachované pôvodné správanie aplikácie.
            battery_capacity_kwh = (
                current_user.battery_capacity or 3
            ) * 1000

            if latest is None:
                return jsonify(
                    {
                        "current_percent": 0,
                        "current_kwh": 0,
                        "battery_capacity_kwh": battery_capacity_kwh,
                        "total_production": 0,
                        "grid_import": 0,
                        "net_balance": 0,
                        "last_update": "Žiadne dáta",
                        "point_alias": point_alias,
                    }
                )

            production = float(latest.production or 0)
            grid_import = float(latest.consumption or 0)
            net_balance = battery_capacity_kwh - production

            current_percent = 0.0
            if battery_capacity_kwh > 0:
                current_percent = min(
                    100.0,
                    max(
                        0.0,
                        production / battery_capacity_kwh * 100,
                    ),
                )

            return jsonify(
                {
                    "current_percent": round(current_percent, 1),
                    "current_kwh": round(production, 1),
                    "battery_capacity_kwh": battery_capacity_kwh,
                    "total_production": round(production, 1),
                    "grid_import": round(grid_import, 1),
                    "net_balance": round(net_balance, 1),
                    "last_update": (
                        latest.date.strftime("%d.%m.%Y")
                        if latest.date
                        else "--"
                    ),
                    "point_alias": point_alias,
                }
            )

        except Exception as exc:
            logger.exception("Načítanie stavu batérie zlyhalo.")
            return jsonify({"error": str(exc)}), 500

    # -----------------------------------------------------------------------
    # CHYBOVÉ ODPOVEDE
    # -----------------------------------------------------------------------

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Požadovaný endpoint neexistuje."}), 404

        return "Stránka neexistuje.", 404

    @app.errorhandler(500)
    def internal_error(_error):
        db.session.rollback()

        if request.path.startswith("/api/"):
            return jsonify({"error": "Interná chyba servera."}), 500

        return "Interná chyba servera.", 500

    # -----------------------------------------------------------------------
    # DATABÁZA
    # -----------------------------------------------------------------------

    @app.cli.command("init-db")
    def init_db_command():
        """Manuálne vytvorí všetky tabuľky: flask --app app init-db"""
        db.create_all()
        print("Databázové tabuľky boli vytvorené.")

    # Dôležité pre Render + gunicorn app:app:
    # tento blok sa vykoná aj pri importe modulu, nielen pri python app.py.
    with app.app_context():
        logger.info(
            "Pripájam databázu: %s",
            hide_database_password(
                app.config["SQLALCHEMY_DATABASE_URI"]
            ),
        )
        db.create_all()
        logger.info("Databázové tabuľky sú pripravené.")

    return app


# Render/Gunicorn používa tento objekt:
# gunicorn app:app
app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug_mode = os.getenv("FLASK_DEBUG", "0") == "1"

    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug_mode,
    )
