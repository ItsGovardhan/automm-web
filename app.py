"""
AutoMM website — escrow (middleman) with automatic Litecoin payments via Apirone.

Run:   python app.py
Admin: python app.py make-admin <username>
"""

import os
import re
import io
import sys
import base64
import secrets
import sqlite3
import asyncio
import threading
import time
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import (Flask, g, render_template, request, redirect, url_for,
                   session, flash, abort, jsonify)
from markupsafe import Markup
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()
import apirone_payment as apr  # noqa: E402

# ═══════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════
BRAND            = os.getenv("BRAND_NAME", "AutoMM")
FEE_PCT          = Decimal(os.getenv("FEE_PERCENTAGE", "2.5"))
DEPOSIT_TIMEOUT  = int(os.getenv("DEPOSIT_TIMEOUT_MINUTES", "60"))
ACCEPT_TIMEOUT_H = int(os.getenv("ACCEPT_TIMEOUT_HOURS", "48"))
MIN_USD          = Decimal(os.getenv("MIN_USD", "1"))
MAX_USD          = Decimal(os.getenv("MAX_USD", "100000"))
POLL_EVERY       = int(os.getenv("POLL_SECONDS", "30"))
DB_PATH          = Path(os.getenv("DB_PATH", "data/automm.db"))

app = Flask(__name__)
_secret = os.getenv("SECRET_KEY")
if not _secret:
    _secret = secrets.token_hex(32)
    print("WARNING: SECRET_KEY .env me set nahi hai. Restart pe sab log logout ho jayenge.")
app.config.update(
    SECRET_KEY=_secret,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
    MAX_CONTENT_LENGTH=64 * 1024,
)
log = logging.getLogger("automm")
logging.basicConfig(level=logging.INFO)


# ═══════════════════════════════════════════════════════════
#  ICONS  (inline SVG, koi emoji nahi)
# ═══════════════════════════════════════════════════════════
ICONS = {
    "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
    "shield-check": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    "lock": '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "user": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "log-out": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    "log-in": '<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><path d="m10 17 5-5-5-5"/><path d="M15 12H3"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "x-circle": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "copy": '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "wallet": '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
    "layout": '<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>',
    "send": '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',
    "external": '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "flag": '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/>',
    "file": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    "arrow-left": '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
    "key": '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "refresh": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
}


def icon(name: str, size: int = 18):
    body = ICONS[name]
    return Markup(
        f'<svg class="i" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{body}</svg>'
    )


STATUS = {
    "pending_accept":   ("Waiting for partner", "wait", "clock"),
    "awaiting_deposit": ("Waiting for payment", "wait", "wallet"),
    "funded":           ("Funds locked",        "ok",   "lock"),
    "releasing":        ("Sending payout",      "wait", "send"),
    "completed":        ("Completed",           "done", "check"),
    "disputed":         ("In dispute",          "bad",  "flag"),
    "cancelled":        ("Cancelled",           "mute", "x-circle"),
    "expired":          ("Expired",             "mute", "clock"),
    "refunded":         ("Refunded",            "mute", "arrow-left"),
}


# ═══════════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════════
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deals (
    id TEXT PRIMARY KEY,
    creator_uid TEXT NOT NULL,
    buyer_uid TEXT NOT NULL,
    seller_uid TEXT NOT NULL,
    usd_amount TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    ltc_amount TEXT, ltc_rate TEXT, fee_ltc TEXT,
    deposit_address TEXT, deposit_txid TEXT,
    received_ltc TEXT, pay_state TEXT,
    seller_address TEXT, payout_txid TEXT,
    dispute_reason TEXT, error TEXT,
    created_at TEXT NOT NULL,
    accepted_at TEXT, deadline TEXT, funded_at TEXT, completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_deals_buyer  ON deals(buyer_uid);
CREATE INDEX IF NOT EXISTS idx_deals_seller ON deals(seller_uid);
CREATE INDEX IF NOT EXISTS idx_deals_status ON deals(status);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id TEXT NOT NULL,
    actor_uid TEXT,
    action TEXT NOT NULL,
    detail TEXT,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_deal ON events(deal_id);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_event(db, deal_id, actor_uid, action, detail=""):
    db.execute("INSERT INTO events (deal_id, actor_uid, action, detail, ts) VALUES (?,?,?,?,?)",
               (deal_id, actor_uid, action, detail, now_iso()))


UID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_uid() -> str:
    return "U-" + "".join(secrets.choice(UID_ALPHABET) for _ in range(8))


def new_deal_id() -> str:
    return "MM-" + secrets.token_hex(6).upper()


# ═══════════════════════════════════════════════════════════
#  TEMPLATE HELPERS
# ═══════════════════════════════════════════════════════════
def get_csrf() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def csrf_input():
    return Markup(f'<input type="hidden" name="csrf" value="{get_csrf()}">')


@app.template_filter("fmt_time")
def fmt_time(value):
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    return dt.strftime("%d %b %Y, %H:%M UTC")


@app.template_filter("usd")
def fmt_usd(value):
    try:
        return f"${Decimal(str(value)):,.2f}"
    except InvalidOperation:
        return str(value)


app.jinja_env.globals.update(icon=icon, csrf_input=csrf_input, BRAND=BRAND,
                             status_meta=STATUS, FEE_PCT=FEE_PCT)


def tracker(deal):
    labels = [("Terms agreed", "file"), ("Payment received", "lock"), ("Funds released", "send")]
    s = deal["status"]
    accepted = bool(deal["accepted_at"])
    funded = bool(deal["funded_at"])
    if s == "pending_accept":
        st = ["current", "todo", "todo"]
    elif s == "awaiting_deposit":
        st = ["done", "current", "todo"]
    elif s in ("funded", "releasing"):
        st = ["done", "done", "current"]
    elif s == "completed":
        st = ["done", "done", "done"]
    elif s == "disputed":
        st = ["done", "done" if funded else "bad", "bad"]
    elif s == "refunded":
        st = ["done", "done", "bad"]
    else:  # cancelled / expired
        st = ["done", "bad", "todo"] if accepted else ["bad", "todo", "todo"]
    return [{"label": l, "icon": i, "state": x} for (l, i), x in zip(labels, st)]


EVENT_TEXT = {
    "created":           "{actor} created the deal",
    "accepted":          "{actor} accepted the terms. Deposit address issued",
    "cancelled":         "{actor} closed the request",
    "deposit_pending":   "Payment seen on the network ({detail} LTC), waiting for confirmations",
    "deposit_underpaid": "Payment received but short ({detail} LTC in total)",
    "funded":            "Payment confirmed ({detail} LTC). Funds are locked",
    "payout_address":    "{actor} set the payout address",
    "released":          "{actor} released the funds",
    "payout_sent":       "Payout sent to the seller",
    "payout_rejected":   "Payout was rejected. Funds are still locked",
    "payout_uncertain":  "Payout status is unclear. Staff will review it",
    "disputed":          "{actor} opened a dispute: {detail}",
    "expired":           "Deal expired",
    "refunded":          "Refund sent to the buyer",
    "admin_release":     "{actor} (staff) released the funds to the seller",
    "admin_refund":      "{actor} (staff) refunded the buyer",
}


def load_events(db, deal_id):
    rows = db.execute(
        "SELECT e.*, u.username FROM events e LEFT JOIN users u ON u.uid = e.actor_uid "
        "WHERE e.deal_id=? ORDER BY e.id DESC", (deal_id,)).fetchall()
    out = []
    for r in rows:
        tpl = EVENT_TEXT.get(r["action"], r["action"])
        text = tpl.format(actor=r["username"] or "System", detail=r["detail"] or "")
        out.append({"ts": r["ts"], "text": text})
    return out


# ═══════════════════════════════════════════════════════════
#  AUTH
# ═══════════════════════════════════════════════════════════
_attempts = {}


def too_many_attempts(key, limit=8, window=600):
    now = time.time()
    hits = [t for t in _attempts.get(key, []) if now - t < window]
    _attempts[key] = hits
    return len(hits) >= limit


def note_attempt(key):
    _attempts.setdefault(key, []).append(time.time())


@app.before_request
def load_user_and_check_csrf():
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = get_db().execute("SELECT * FROM users WHERE uid=?", (uid,)).fetchone()
        if g.user is None:
            session.clear()
    if request.method == "POST":
        token = session.get("csrf", "")
        sent = request.form.get("csrf", "")
        if not token or not secrets.compare_digest(token, sent):
            abort(400)


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        return fn(*a, **kw)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*a, **kw):
        if not g.user["is_admin"]:
            abort(404)
        return fn(*a, **kw)
    return wrapper


@app.errorhandler(400)
def err400(_e):
    return render_template("error.html", code=400,
                           msg="This form expired. Go back, refresh the page and try again."), 400


@app.errorhandler(404)
def err404(_e):
    return render_template("error.html", code=404, msg="That page doesn't exist."), 404


@app.errorhandler(413)
def err413(_e):
    return render_template("error.html", code=413, msg="That request was too large."), 413


@app.errorhandler(500)
def err500(_e):
    return render_template("error.html", code=500, msg="Something broke on our side. Try again in a moment."), 500


@app.route("/")
def home():
    if g.user:
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        db = get_db()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):
            flash("Username must be 3 to 20 characters: letters, numbers or underscore.", "error")
        elif len(pw) < 8 or len(pw) > 128:
            flash("Password must be at least 8 characters.", "error")
        elif db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            flash("That username is taken. Pick another one.", "error")
        else:
            created = None
            for _ in range(10):
                uid = new_uid()
                try:
                    db.execute("INSERT INTO users (uid, username, pw_hash, created_at) VALUES (?,?,?,?)",
                               (uid, username, generate_password_hash(pw), now_iso()))
                    db.commit()
                    created = uid
                    break
                except sqlite3.IntegrityError:
                    db.rollback()
                    if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                        break
            if created:
                session.clear()
                session["uid"] = created
                session.permanent = True
                flash("Account created. Your User ID is in the sidebar. Share it so others can start a deal with you.", "ok")
                return redirect(url_for("dashboard"))
            flash("That username is taken. Pick another one.", "error")
    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        key = f"{request.remote_addr}:{username.lower()}"
        if too_many_attempts(key):
            flash("Too many attempts. Wait 10 minutes and try again.", "error")
        else:
            row = get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            if row and check_password_hash(row["pw_hash"], pw):
                session.clear()
                session["uid"] = row["uid"]
                session.permanent = True
                nxt = request.args.get("next", "")
                if not (nxt.startswith("/") and not nxt.startswith("//")):
                    nxt = url_for("dashboard")
                return redirect(nxt)
            note_attempt(key)
            flash("Wrong username or password.", "error")
    return render_template("auth.html", mode="login")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ═══════════════════════════════════════════════════════════
#  DASHBOARD / CREATE MM
# ═══════════════════════════════════════════════════════════
@app.route("/dashboard")
@login_required
def dashboard():
    uid = g.user["uid"]
    deals = get_db().execute(
        "SELECT * FROM deals WHERE buyer_uid=? OR seller_uid=? ORDER BY created_at DESC LIMIT 100",
        (uid, uid)).fetchall()
    active = sum(1 for d in deals if d["status"] in ("pending_accept", "awaiting_deposit", "funded", "releasing"))
    done = sum(1 for d in deals if d["status"] == "completed")
    disputed = sum(1 for d in deals if d["status"] == "disputed")
    return render_template("dashboard.html", deals=deals, active=active, done=done, disputed=disputed)


@app.route("/mm/new", methods=["GET", "POST"])
@login_required
def new_mm():
    form = {"partner": "", "role": "buyer", "amount": "", "description": ""}
    if request.method == "POST":
        form["partner"] = request.form.get("partner", "").strip().upper()
        form["role"] = request.form.get("role", "buyer")
        form["amount"] = request.form.get("amount", "").strip()
        form["description"] = request.form.get("description", "").strip()
        db = get_db()
        error = None
        partner = db.execute("SELECT * FROM users WHERE uid=?", (form["partner"],)).fetchone()
        try:
            amount = Decimal(form["amount"]).quantize(Decimal("0.01"))
        except InvalidOperation:
            amount = None
        if form["role"] not in ("buyer", "seller"):
            error = "Choose whether you are the buyer or the seller."
        elif partner is None:
            error = "No user has that User ID. Check it with the other person."
        elif partner["uid"] == g.user["uid"]:
            error = "You can't start a deal with yourself."
        elif amount is None or not (MIN_USD <= amount <= MAX_USD):
            error = f"Enter an amount between ${MIN_USD} and ${MAX_USD:,}."
        elif not (5 <= len(form["description"]) <= 500):
            error = "Describe what is being traded in 5 to 500 characters."
        if error:
            flash(error, "error")
        else:
            buyer, seller = ((g.user["uid"], partner["uid"]) if form["role"] == "buyer"
                             else (partner["uid"], g.user["uid"]))
            deal_id = new_deal_id()
            db.execute(
                "INSERT INTO deals (id, creator_uid, buyer_uid, seller_uid, usd_amount, description, status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (deal_id, g.user["uid"], buyer, seller, str(amount), form["description"],
                 "pending_accept", now_iso()))
            log_event(db, deal_id, g.user["uid"], "created")
            db.commit()
            return redirect(url_for("deal_page", deal_id=deal_id))
    return render_template("new.html", form=form, min_usd=MIN_USD, max_usd=MAX_USD)


# ═══════════════════════════════════════════════════════════
#  DEAL PAGE + ACTIONS
# ═══════════════════════════════════════════════════════════
def load_deal(deal_id):
    deal = get_db().execute("SELECT * FROM deals WHERE id=?", (deal_id.upper(),)).fetchone()
    if deal is None:
        abort(404)
    is_party = g.user["uid"] in (deal["buyer_uid"], deal["seller_uid"])
    if not is_party and not g.user["is_admin"]:
        abort(404)   # deal ka wajood bhi leak nahi karte
    return deal


def party_only(deal):
    if g.user["uid"] not in (deal["buyer_uid"], deal["seller_uid"]):
        abort(404)


def qr_data_uri(address, amount):
    png = apr.make_qr(address, Decimal(str(amount)))
    return "data:image/png;base64," + base64.b64encode(png).decode()


@app.route("/mm/<deal_id>")
@login_required
def deal_page(deal_id):
    deal = load_deal(deal_id)
    db = get_db()
    uid = g.user["uid"]
    is_buyer, is_seller = uid == deal["buyer_uid"], uid == deal["seller_uid"]
    people = {r["uid"]: r["username"] for r in db.execute(
        "SELECT uid, username FROM users WHERE uid IN (?,?)",
        (deal["buyer_uid"], deal["seller_uid"])).fetchall()}
    partner_uid = deal["seller_uid"] if deal["creator_uid"] == deal["buyer_uid"] else deal["buyer_uid"]
    qr = short = seller_gets = None
    if deal["ltc_amount"]:
        seller_gets = (Decimal(deal["ltc_amount"]) - Decimal(deal["fee_ltc"])).quantize(Decimal("0.00000001"))
    if deal["status"] == "awaiting_deposit":
        if is_buyer:
            qr = qr_data_uri(deal["deposit_address"], deal["ltc_amount"])
        if deal["pay_state"] == "underpaid" and deal["received_ltc"]:
            short = (Decimal(deal["ltc_amount"]) - Decimal(deal["received_ltc"])).quantize(Decimal("0.00000001"))
    return render_template(
        "deal.html", deal=deal, steps=tracker(deal), events=load_events(db, deal["id"]),
        buyer_name=people.get(deal["buyer_uid"], "?"), seller_name=people.get(deal["seller_uid"], "?"),
        is_buyer=is_buyer, is_seller=is_seller, is_admin=bool(g.user["is_admin"]),
        can_accept=(deal["status"] == "pending_accept" and uid == partner_uid),
        qr=qr, short=short, seller_gets=seller_gets,
        watch_state=f"{deal['status']}|{deal['pay_state'] or ''}|{deal['received_ltc'] or ''}",
    )


@app.route("/api/mm/<deal_id>/status")
@login_required
def deal_status(deal_id):
    deal = load_deal(deal_id)
    return jsonify(status=deal["status"], pay_state=deal["pay_state"] or "",
                   received=deal["received_ltc"] or "")


@app.post("/mm/<deal_id>/accept")
@login_required
def accept(deal_id):
    deal = load_deal(deal_id)
    partner_uid = deal["seller_uid"] if deal["creator_uid"] == deal["buyer_uid"] else deal["buyer_uid"]
    if deal["status"] != "pending_accept" or g.user["uid"] != partner_uid:
        abort(404)
    try:
        price = asyncio.run(apr.ltc_price_usd())
        address = asyncio.run(apr.apirone_generate_address())
    except Exception:
        log.exception("accept: price/address failed")
        flash("Couldn't create the deposit address right now. Try again in a minute.", "error")
        return redirect(url_for("deal_page", deal_id=deal["id"]))
    ltc = apr.usd_to_ltc(Decimal(deal["usd_amount"]), price)
    fee = (ltc * FEE_PCT / 100).quantize(Decimal("0.00000001"))
    deadline = (datetime.now(timezone.utc) + timedelta(minutes=DEPOSIT_TIMEOUT)).isoformat(timespec="seconds")
    db = get_db()
    cur = db.execute(
        "UPDATE deals SET status='awaiting_deposit', ltc_amount=?, ltc_rate=?, fee_ltc=?, "
        "deposit_address=?, accepted_at=?, deadline=? WHERE id=? AND status='pending_accept'",
        (str(ltc), str(price), str(fee), address, now_iso(), deadline, deal["id"]))
    if cur.rowcount == 1:
        log_event(db, deal["id"], g.user["uid"], "accepted")
        flash("Terms accepted. The buyer can pay now.", "ok")
    db.commit()
    return redirect(url_for("deal_page", deal_id=deal["id"]))


@app.post("/mm/<deal_id>/cancel")
@login_required
def cancel(deal_id):
    deal = load_deal(deal_id)
    party_only(deal)
    db = get_db()
    cur = db.execute("UPDATE deals SET status='cancelled' WHERE id=? AND status='pending_accept'", (deal["id"],))
    if cur.rowcount == 1:
        log_event(db, deal["id"], g.user["uid"], "cancelled")
        flash("Deal closed.", "ok")
    db.commit()
    return redirect(url_for("deal_page", deal_id=deal["id"]))


@app.post("/mm/<deal_id>/payout-address")
@login_required
def set_payout_address(deal_id):
    deal = load_deal(deal_id)
    if g.user["uid"] != deal["seller_uid"] or deal["status"] not in ("awaiting_deposit", "funded", "disputed"):
        abort(404)
    addr = request.form.get("address", "").strip()
    if not apr.valid_ltc_addr(addr):
        flash("That doesn't look like a Litecoin address (starts with L, M or ltc1).", "error")
    else:
        db = get_db()
        db.execute("UPDATE deals SET seller_address=? WHERE id=?", (addr, deal["id"]))
        log_event(db, deal["id"], g.user["uid"], "payout_address")
        db.commit()
        flash("Payout address saved.", "ok")
    return redirect(url_for("deal_page", deal_id=deal["id"]))


def run_payout(db, deal, from_status, busy_status, to_addr, amount, done_status, actor_uid, done_event, pre_event=None):
    """Atomic payout: status pehle 'busy' lock hota hai, taaki double-click se double payment na ho."""
    cur = db.execute("UPDATE deals SET status=? WHERE id=? AND status=?", (busy_status, deal["id"], from_status))
    db.commit()
    if cur.rowcount != 1:
        return "busy"
    if pre_event:
        log_event(db, deal["id"], actor_uid, pre_event)
        db.commit()
    try:
        txid = asyncio.run(apr.apirone_send_ltc(to_addr, amount))
    except apr.ApironeRejected as e:
        log.error("payout rejected %s: %s", deal["id"], e)
        db.execute("UPDATE deals SET status=?, error=? WHERE id=?", (from_status, str(e)[:400], deal["id"]))
        log_event(db, deal["id"], None, "payout_rejected")
        db.commit()
        return "rejected"
    except Exception as e:
        log.exception("payout unclear %s", deal["id"])
        db.execute("UPDATE deals SET status='disputed', dispute_reason=?, error=? WHERE id=?",
                   ("Payout status unclear, check Apirone before retrying", str(e)[:400], deal["id"]))
        log_event(db, deal["id"], None, "payout_uncertain")
        db.commit()
        return "uncertain"
    db.execute("UPDATE deals SET status=?, payout_txid=?, completed_at=? WHERE id=?",
               (done_status, txid, now_iso(), deal["id"]))
    log_event(db, deal["id"], actor_uid, done_event, txid)
    db.commit()
    return "ok"


def payout_flash(result, ok_msg):
    if result == "ok":
        flash(ok_msg, "ok")
    elif result == "rejected":
        flash("The payout was rejected. The funds are still locked. Try again or contact staff.", "error")
    elif result == "uncertain":
        flash("The payout status is unclear. Staff will check it before anything is sent again.", "error")
    else:
        flash("This deal is already being processed.", "error")


@app.post("/mm/<deal_id>/release")
@login_required
def release(deal_id):
    deal = load_deal(deal_id)
    if g.user["uid"] != deal["buyer_uid"] or deal["status"] != "funded":
        abort(404)
    if not deal["seller_address"]:
        flash("The seller hasn't added a payout address yet.", "error")
        return redirect(url_for("deal_page", deal_id=deal["id"]))
    amount = (Decimal(deal["ltc_amount"]) - Decimal(deal["fee_ltc"])).quantize(Decimal("0.00000001"))
    db = get_db()
    res = run_payout(db, deal, "funded", "releasing", deal["seller_address"], amount,
                     "completed", g.user["uid"], "payout_sent", pre_event="released")
    payout_flash(res, "Funds released. The seller has been paid.")
    return redirect(url_for("deal_page", deal_id=deal["id"]))


@app.post("/mm/<deal_id>/dispute")
@login_required
def dispute(deal_id):
    deal = load_deal(deal_id)
    party_only(deal)
    reason = request.form.get("reason", "").strip()
    if not (5 <= len(reason) <= 500):
        flash("Explain the problem in 5 to 500 characters.", "error")
        return redirect(url_for("deal_page", deal_id=deal["id"]))
    db = get_db()
    cur = db.execute("UPDATE deals SET status='disputed', dispute_reason=? WHERE id=? AND status='funded'",
                     (reason, deal["id"]))
    if cur.rowcount == 1:
        log_event(db, deal["id"], g.user["uid"], "disputed", reason)
        flash("Dispute opened. The funds are frozen until staff decide.", "ok")
    db.commit()
    return redirect(url_for("deal_page", deal_id=deal["id"]))


# ═══════════════════════════════════════════════════════════
#  ADMIN
# ═══════════════════════════════════════════════════════════
@app.route("/admin")
@admin_required
def admin():
    db = get_db()
    disputed = db.execute("SELECT * FROM deals WHERE status='disputed' ORDER BY created_at DESC").fetchall()
    recent = db.execute("SELECT * FROM deals ORDER BY created_at DESC LIMIT 30").fetchall()
    return render_template("admin.html", disputed=disputed, recent=recent)


@app.post("/admin/mm/<deal_id>/release")
@admin_required
def admin_release(deal_id):
    deal = load_deal(deal_id)
    if deal["status"] != "disputed" or not deal["ltc_amount"] or not deal["funded_at"]:
        abort(404)
    if not deal["seller_address"]:
        flash("The seller has no payout address saved.", "error")
        return redirect(url_for("admin"))
    amount = (Decimal(deal["ltc_amount"]) - Decimal(deal["fee_ltc"])).quantize(Decimal("0.00000001"))
    db = get_db()
    res = run_payout(db, deal, "disputed", "releasing", deal["seller_address"], amount,
                     "completed", g.user["uid"], "admin_release")
    payout_flash(res, "Released to the seller.")
    return redirect(url_for("admin"))


@app.post("/admin/mm/<deal_id>/refund")
@admin_required
def admin_refund(deal_id):
    deal = load_deal(deal_id)
    if deal["status"] != "disputed" or not deal["received_ltc"]:
        abort(404)
    addr = request.form.get("address", "").strip()
    if not apr.valid_ltc_addr(addr):
        flash("That doesn't look like a Litecoin address.", "error")
        return redirect(url_for("admin"))
    db = get_db()
    res = run_payout(db, deal, "disputed", "releasing", addr, Decimal(deal["received_ltc"]),
                     "refunded", g.user["uid"], "admin_refund")
    payout_flash(res, "Refund sent to the buyer.")
    return redirect(url_for("admin"))


# ═══════════════════════════════════════════════════════════
#  BACKGROUND POLLER  (automatic payment detection)
#  DB-based hai, isliye server restart ke baad bhi chalta rehta hai.
# ═══════════════════════════════════════════════════════════
def poll_once():
    db = connect()
    try:
        # Jis request ka jawab partner ne 48h me nahi diya
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=ACCEPT_TIMEOUT_H)).isoformat(timespec="seconds")
        for r in db.execute("SELECT id FROM deals WHERE status='pending_accept' AND created_at < ?", (cutoff,)).fetchall():
            if db.execute("UPDATE deals SET status='expired' WHERE id=? AND status='pending_accept'", (r["id"],)).rowcount:
                log_event(db, r["id"], None, "expired")
        db.commit()

        for d in db.execute("SELECT * FROM deals WHERE status='awaiting_deposit'").fetchall():
            try:
                state, txid, received = asyncio.run(
                    apr.check_deposit_once(d["deposit_address"], Decimal(d["ltc_amount"])))
            except Exception as e:
                log.warning("poll %s skipped: %s", d["id"], e)
                continue

            if state == "confirmed":
                cur = db.execute(
                    "UPDATE deals SET status='funded', deposit_txid=?, received_ltc=?, pay_state='confirmed', funded_at=? "
                    "WHERE id=? AND status='awaiting_deposit'", (txid, str(received), now_iso(), d["id"]))
                if cur.rowcount == 1:
                    log_event(db, d["id"], None, "funded", str(received))
            elif state in ("pending", "underpaid"):
                if d["pay_state"] != state or d["received_ltc"] != str(received):
                    db.execute("UPDATE deals SET pay_state=?, deposit_txid=?, received_ltc=? "
                               "WHERE id=? AND status='awaiting_deposit'", (state, txid, str(received), d["id"]))
                    log_event(db, d["id"], None, "deposit_pending" if state == "pending" else "deposit_underpaid", str(received))
            if state in ("none", "underpaid", "pending") and d["deadline"] and \
                    datetime.now(timezone.utc) > datetime.fromisoformat(d["deadline"]):
                if state == "none":
                    if db.execute("UPDATE deals SET status='expired' WHERE id=? AND status='awaiting_deposit'",
                                  (d["id"],)).rowcount:
                        log_event(db, d["id"], None, "expired")
                elif state == "underpaid":
                    # Kam paisa aaya aur time khatam: staff refund kar sakein isliye dispute me daalo
                    if db.execute("UPDATE deals SET status='disputed', dispute_reason=? WHERE id=? AND status='awaiting_deposit'",
                                  ("Underpaid deposit after the deadline", d["id"])).rowcount:
                        log_event(db, d["id"], None, "disputed", "Underpaid deposit after the deadline")
            db.commit()
    finally:
        db.close()


_poller_started = False


def start_poller():
    global _poller_started
    if _poller_started:
        return
    _poller_started = True

    def loop():
        while True:
            try:
                poll_once()
            except Exception:
                log.exception("poller crashed, retrying")
            time.sleep(POLL_EVERY)

    threading.Thread(target=loop, name="deposit-poller", daemon=True).start()
    log.info("Deposit poller started (every %ss)", POLL_EVERY)


init_db()
if __name__ != "__main__" and os.getenv("START_POLLER", "1") == "1":
    start_poller()   # gunicorn / wsgi ke liye


def require_env():
    missing = [k for k in ("APIRONE_ACCOUNT", "APIRONE_TRANSFER_KEY") if not os.getenv(k)]
    if missing:
        raise SystemExit(f".env me ye set karo: {', '.join(missing)}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "make-admin":
        conn = connect()
        n = conn.execute("UPDATE users SET is_admin=1 WHERE username=?", (sys.argv[2],)).rowcount
        conn.commit()
        print("Admin bana diya." if n else "Ye username nahi mila.")
        raise SystemExit
    require_env()
    start_poller()
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")), debug=False)
