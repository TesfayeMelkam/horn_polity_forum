"""Membership plans, payment methods (Telebirr / bank transfer / Chapa online), orders and member sign-in.

How money flows
---------------
* MANUAL methods (Telebirr number, bank account ...): the visitor sends money, then submits the
  transaction ID and/or a screenshot. An admin checks it and clicks Approve -> membership activates.
* ONLINE method (Chapa: Telebirr, CBE Birr, cards, banks): the visitor is redirected to Chapa's secure
  page. We ALWAYS verify the result server-to-server before activating (never trust the browser).
  Needs CHAPA_SECRET_KEY in the environment or in the .env file.
"""
import base64
import hmac
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, send_from_directory, session

from common import (admin_required, error, parse_utc, rate_limit, safe_url, text, valid_email)
from database import PROOF_DIR, db, get_setting, set_setting, utcnow

bp = Blueprint("payments", __name__)

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CURRENCIES = ("ETB", "USD", "EUR")
MANUAL_KINDS = ("telebirr", "bank", "cbebirr", "mpesa", "wire", "payoneer", "alipay_qr", "other")
STRIPE_KINDS = ("stripe", "card", "alipay")      # all use Stripe Checkout (card = Visa/Mastercard only, alipay = Alipay only)
ONLINE_KINDS = ("chapa", "paypal") + STRIPE_KINDS
PROOF_EXT = {"jpg", "jpeg", "png", "webp", "pdf"}
CHAPA_BASE = "https://api.chapa.co"


def rand(n):
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def chapa_key():
    return os.environ.get("CHAPA_SECRET_KEY", "").strip()


def public_base():
    return (os.environ.get("HPF_PUBLIC_URL", "").strip() or request.host_url).rstrip("/")


def chapa_request(method, path, payload=None):
    """Call the Chapa API. Returns (http_status, parsed_json_or_None). Kept separate so tests can mock it."""
    req = urllib.request.Request(
        CHAPA_BASE + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": "Bearer " + chapa_key(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "null")
        except Exception:
            return e.code, None
    except Exception:
        return 0, None


def stripe_key():
    return os.environ.get("STRIPE_SECRET_KEY", "").strip()


def paypal_ready():
    return bool(os.environ.get("PAYPAL_CLIENT_ID", "").strip() and os.environ.get("PAYPAL_CLIENT_SECRET", "").strip())


def paypal_base():
    live = os.environ.get("PAYPAL_MODE", "sandbox").strip().lower() == "live"
    return "https://api-m.paypal.com" if live else "https://api-m.sandbox.paypal.com"


def _http(req):
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "null")
        except Exception:
            return e.code, None
    except Exception:
        return 0, None


def stripe_request(method, path, data=None):
    """Stripe REST API (form-encoded). Separate function so tests can mock it."""
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request("https://api.stripe.com" + path, data=body, method=method,
                                 headers={"Authorization": "Bearer " + stripe_key(),
                                          "Content-Type": "application/x-www-form-urlencoded"})
    return _http(req)


_pp_token = {"value": "", "exp": 0}


def paypal_request(method, path, payload=None):
    """PayPal Orders v2 API with OAuth2 client-credentials. Mockable for tests."""
    if time.time() > _pp_token["exp"]:
        cred = base64.b64encode((os.environ.get("PAYPAL_CLIENT_ID", "") + ":" + os.environ.get("PAYPAL_CLIENT_SECRET", "")).encode()).decode()
        st, tok = _http(urllib.request.Request(paypal_base() + "/v1/oauth2/token", data=b"grant_type=client_credentials", method="POST",
                                               headers={"Authorization": "Basic " + cred, "Content-Type": "application/x-www-form-urlencoded"}))
        if st != 200 or not tok:
            return 0, None
        _pp_token.update(value=tok["access_token"], exp=time.time() + int(tok.get("expires_in", 300)) - 30)
    req = urllib.request.Request(paypal_base() + path, method=method, data=json.dumps(payload if payload is not None else {}).encode() if method == "POST" else None,
                                 headers={"Authorization": "Bearer " + _pp_token["value"], "Content-Type": "application/json"})
    return _http(req)


def price_for(plan, cur):
    return {"ETB": plan["price_etb"], "USD": plan["price_usd"], "EUR": plan["price_eur"]}.get(cur, 0)


def req_approval(conn):
    return get_setting(conn, "online_requires_approval", "0") == "1"


# ------------------------------------------------------------------ public: plans & methods
def plan_dict(r):
    return {"key": r["key"], "name": r["name"], "priceEtb": r["price_etb"], "periodDays": r["period_days"],
            "priceUsd": r["price_usd"], "priceEur": r["price_eur"],
            "benefits": r["benefits"], "custom": bool(r["custom"]), "active": bool(r["active"])}


def method_available(m):
    if not m["enabled"]:
        return False
    if m["kind"] == "chapa":
        return bool(chapa_key())
    if m["kind"] in STRIPE_KINDS:
        return bool(stripe_key())
    if m["kind"] == "paypal":
        return paypal_ready()
    return bool(m["account_number"].strip())


def method_public(m):
    return {"id": m["id"], "kind": m["kind"], "label": m["label"], "online": m["kind"] in ONLINE_KINDS,
            "currencies": [c for c in m["currencies"].split(",") if c in CURRENCIES] or ["ETB"],
            "accountName": m["account_name"], "accountNumber": m["account_number"],
            "instructions": m["instructions"], "payLink": m["pay_link"], "qrUrl": m["qr_url"]}


@bp.route("/api/plans")
def plans():
    with db() as conn:
        pl = conn.execute("SELECT * FROM plans WHERE active = 1 ORDER BY sort, key").fetchall()
        ms = conn.execute("SELECT * FROM payment_methods ORDER BY sort, id").fetchall()
    return jsonify({"plans": [plan_dict(p) for p in pl], "currencies": list(CURRENCIES),
                    "methods": [method_public(m) for m in ms if method_available(m)]})


# ------------------------------------------------------------------ members
def member_dict(m):
    with db() as conn:
        p = conn.execute("SELECT name FROM plans WHERE key = ?", (m["plan"],)).fetchone()
    active = m["status"] == "active" and (not m["expires_at"] or m["expires_at"] > utcnow())
    return {"name": m["name"], "email": m["email"], "plan": m["plan"], "planName": p["name"] if p else m["plan"],
            "status": m["status"], "active": active, "expiresAt": m["expires_at"]}


def activate_member(conn, member_id, plan_key, days):
    m = conn.execute("SELECT expires_at FROM members WHERE id = ?", (member_id,)).fetchone()
    base = datetime.now(timezone.utc)
    if m and m["expires_at"] and m["expires_at"] > utcnow():
        base = parse_utc(m["expires_at"])
    exp = (base + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ") if days > 0 else None
    conn.execute("UPDATE members SET plan = ?, tier = ?, status = 'active', expires_at = ? WHERE id = ?",
                 (plan_key, plan_key, exp, member_id))


def mark_paid(conn, order, note=""):
    plan = conn.execute("SELECT period_days FROM plans WHERE key = ?", (order["plan"],)).fetchone()
    days = plan["period_days"] if plan else 30
    now = utcnow()
    conn.execute("UPDATE orders SET status='paid', paid_at=?, updated_at=?, note=? WHERE id=?",
                 (now, now, note or order["note"], order["id"]))
    activate_member(conn, order["member_id"], order["plan"], days)


@bp.route("/api/member/login", methods=["POST"])
@rate_limit(8, 60)
def member_login():
    d = request.get_json(silent=True) or {}
    email = text(d.get("email"), 254).lower()
    code = re.sub(r"[\s]", "", text(d.get("code"), 30)).upper()
    with db() as conn:
        m = conn.execute("SELECT * FROM members WHERE email = ?", (email,)).fetchone()
    stored = (m["access_code"] or "") if m else ""
    ok = bool(m) and bool(stored) and hmac.compare_digest(stored.replace("-", ""), code.replace("-", ""))
    if not ok:
        return error("Email or access code is not correct", 401)
    session["member_id"] = m["id"]
    return jsonify({"member": member_dict(m)})


@bp.route("/api/member/logout", methods=["POST"])
def member_logout():
    session.pop("member_id", None)
    return jsonify({"ok": True})


@bp.route("/api/member/me")
def member_me():
    mid = session.get("member_id")
    if not mid:
        return jsonify({"member": None})
    with db() as conn:
        m = conn.execute("SELECT * FROM members WHERE id = ?", (mid,)).fetchone()
    return jsonify({"member": member_dict(m) if m else None})


# ------------------------------------------------------------------ checkout
def new_ref(conn):
    while True:
        ref = "HPF-" + rand(8)
        if conn.execute("SELECT 1 FROM orders WHERE ref = ?", (ref,)).fetchone() is None:
            return ref


@bp.route("/api/checkout", methods=["POST"])
@rate_limit(8, 60)
def checkout():
    d = request.get_json(silent=True) or {}
    name, email = text(d.get("name"), 120), text(d.get("email"), 254).lower()
    aff, plan_key = text(d.get("affiliation"), 200), text(d.get("plan"), 30).lower()
    method_id = d.get("methodId")
    cur = text(d.get("currency") or "ETB", 3).upper()
    if cur not in CURRENCIES:
        return error("Unsupported currency")
    if not name:
        return error("Please enter your full name")
    if not valid_email(email):
        return error("A valid email is required")

    with db() as conn:
        plan = conn.execute("SELECT * FROM plans WHERE key = ? AND active = 1", (plan_key,)).fetchone()
        if plan is None:
            return error("Unknown plan")
        if plan["custom"]:
            return error("This plan is by arrangement - please use the Contact page.")
        paid_plan = plan["price_etb"] > 0
        method = None
        if paid_plan:
            amount = price_for(plan, cur)
            if amount <= 0:
                return error("This plan is not offered in " + cur)
            method = conn.execute("SELECT * FROM payment_methods WHERE id = ?",
                                  (method_id if isinstance(method_id, int) else -1,)).fetchone()
            if method is None or not method_available(method):
                return error("Please choose an available payment method")
            if cur not in method["currencies"].split(","):
                return error(method["label"] + " does not accept " + cur)

        member = conn.execute("SELECT * FROM members WHERE email = ?", (email,)).fetchone()
        code = None
        if member is None:
            code = rand(4) + "-" + rand(4)
            mid = conn.execute(
                "INSERT INTO members (name,email,affiliation,tier,plan,status,access_code,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)", (name, email, aff, "reader", "reader", "active", code, utcnow())).lastrowid
        else:
            mid = member["id"]
            conn.execute("UPDATE members SET name = ?, affiliation = ? WHERE id = ?", (name, aff, mid))

        if not paid_plan:
            return jsonify({"free": True, "accessCode": code, "existing": member is not None}), 201

        ref = new_ref(conn)
        amount_minor = amount * 100
        k = method["kind"]
        provider = "stripe" if k in STRIPE_KINDS else (k if k in ("chapa", "paypal") else "manual")
        now = utcnow()
        conn.execute(
            "INSERT INTO orders (ref,member_id,plan,method_id,provider,method_label,currency,amount_minor,status,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ref, mid, plan_key, method["id"], provider, method["label"], cur, amount_minor, "pending", now, now))
        out = {"ref": ref, "accessCode": code, "existing": member is not None, "provider": provider}

        if provider in ONLINE_KINDS:
            url, pref = start_online(provider, ref, name, email, plan, amount, cur, method["kind"])
            if url:
                conn.execute("UPDATE orders SET checkout_url = ?, provider_ref = ? WHERE ref = ?", (url, pref, ref))
                out["checkoutUrl"] = url
            else:
                conn.execute("UPDATE orders SET status='failed', note=?, updated_at=? WHERE ref=?",
                             ("Could not start online payment", utcnow(), ref))
                return error("Could not start the online payment. Please try again or choose another method.", 502)
        return jsonify(out), 201


def start_online(provider, ref, name, email, plan, amount, cur, kind="stripe"):
    """Create a hosted checkout at the gateway. Returns (checkout_url, provider_reference) or (None, None)."""
    back = public_base() + "/pay/" + ref
    if provider == "chapa":
        first, _, last = name.partition(" ")
        desc = re.sub(r"[^A-Za-z0-9 ._-]", "", plan["name"] + " membership")[:60]
        payload = {"amount": str(amount), "currency": "ETB", "email": email, "first_name": first[:50] or "Member",
                   "last_name": last[:50] or "Member", "tx_ref": ref, "return_url": back,
                   "customization": {"title": "Horn Polity", "description": desc}}
        if os.environ.get("HPF_PUBLIC_URL"):
            payload["callback_url"] = public_base() + "/api/chapa/callback"
        st, resp = chapa_request("POST", "/v1/transaction/initialize", payload)
        url = ((resp or {}).get("data") or {}).get("checkout_url")
        return (url, ref) if st == 200 and url else (None, None)
    if provider == "stripe":
        data = {"mode": "payment", "success_url": back + "?paid=1", "cancel_url": back + "?cancelled=1",
                "client_reference_id": ref, "customer_email": email, "metadata[ref]": ref,
                "line_items[0][quantity]": "1", "line_items[0][price_data][currency]": cur.lower(),
                "line_items[0][price_data][unit_amount]": str(amount * 100),
                "line_items[0][price_data][product_data][name]": plan["name"] + " membership - Horn Polity Forum"}
        if kind == "card":
            data["payment_method_types[0]"] = "card"          # Visa / Mastercard only
        elif kind == "alipay":
            data["payment_method_types[0]"] = "alipay"        # Alipay only (must be activated in your Stripe dashboard)
        st, resp = stripe_request("POST", "/v1/checkout/sessions", data)
        url, sid = (resp or {}).get("url"), (resp or {}).get("id")
        return (url, sid) if st == 200 and url and sid else (None, None)
    if provider == "paypal":
        payload = {"intent": "CAPTURE", "purchase_units": [{"reference_id": ref, "description": plan["name"] + " membership",
                   "amount": {"currency_code": cur, "value": "%.2f" % amount}}],
                   "application_context": {"return_url": back, "cancel_url": back + "?cancelled=1", "user_action": "PAY_NOW",
                                           "brand_name": "Horn Polity Forum"}}
        st, resp = paypal_request("POST", "/v2/checkout/orders", payload)
        link = next((l.get("href") for l in (resp or {}).get("links", []) if l.get("rel") in ("approve", "payer-action")), None)
        return (link, resp.get("id")) if st in (200, 201) and link else (None, None)
    return None, None


def order_public(o, m):
    d = {"ref": o["ref"], "status": o["status"], "plan": o["plan"], "provider": o["provider"],
         "amountMinor": o["amount_minor"], "currency": o["currency"], "txRef": o["tx_ref"] or "",
         "hasProof": bool(o["proof_file"]), "note": o["note"] or "", "createdAt": o["created_at"],
         "checkoutUrl": o["checkout_url"] if o["status"] == "pending" else None, "method": None}
    if m is not None and o["provider"] == "manual":
        d["method"] = {"kind": m["kind"], "label": m["label"], "accountName": m["account_name"],
                       "accountNumber": m["account_number"], "instructions": m["instructions"],
                       "payLink": m["pay_link"], "qrUrl": m["qr_url"]}
    return d


def get_order(conn, ref):
    o = conn.execute("SELECT * FROM orders WHERE ref = ?", (text(ref, 20).upper(),)).fetchone()
    m = conn.execute("SELECT * FROM payment_methods WHERE id = ?", (o["method_id"],)).fetchone() if o else None
    return o, m


@bp.route("/api/orders/<ref>")
@rate_limit(60, 60)
def order_status(ref):
    with db() as conn:
        o, m = get_order(conn, ref)
        if o is None:
            return error("Order not found", 404)
        plan = conn.execute("SELECT name FROM plans WHERE key = ?", (o["plan"],)).fetchone()
        d = order_public(o, m)
        d["planName"] = plan["name"] if plan else o["plan"]
        return jsonify(d)


@bp.route("/api/orders/<ref>/proof", methods=["POST"])
@rate_limit(10, 60)
def submit_proof(ref):
    tx = text(request.form.get("tx_ref"), 80)
    f = request.files.get("file")
    with db() as conn:
        o, m = get_order(conn, ref)
        if o is None:
            return error("Order not found", 404)
        if o["provider"] != "manual" or o["status"] not in ("pending", "submitted", "rejected"):
            return error("This order cannot accept payment proof")
        if not tx and (f is None or not f.filename):
            return error("Enter the transaction ID from your receipt or upload a screenshot")
        proof, pname = o["proof_file"], o["proof_name"]
        if f is not None and f.filename:
            from content import save_upload
            stored, original, _ext, err = save_upload(f, PROOF_DIR, PROOF_EXT)
            if err:
                return error(err)
            if proof:
                try:
                    (PROOF_DIR / proof).unlink()
                except OSError:
                    pass
            proof, pname = stored, original
        conn.execute("UPDATE orders SET tx_ref=?, proof_file=?, proof_name=?, status='submitted', note=NULL, updated_at=? WHERE id=?",
                     (tx or o["tx_ref"], proof, pname, utcnow(), o["id"]))
        o, m = get_order(conn, ref)
        return jsonify(order_public(o, m))


def finish_online(conn, o, provider_name):
    """Online payment confirmed by the gateway. Admin may require manual permission first."""
    if req_approval(conn):
        conn.execute("UPDATE orders SET status='submitted', note=?, updated_at=? WHERE id=?",
                     ("Paid online via " + provider_name + " - waiting for admin approval", utcnow(), o["id"]))
        return "submitted"
    mark_paid(conn, o, "Verified with " + provider_name)
    return "paid"


def fail_order(conn, o, note):
    conn.execute("UPDATE orders SET status='failed', note=?, updated_at=? WHERE id=?", (note, utcnow(), o["id"]))
    return "failed"


def verify_with_chapa(conn, o):
    """Server-to-server check. Activates only if Chapa confirms the exact amount in ETB."""
    status, resp = chapa_request("GET", "/v1/transaction/verify/" + o["ref"])
    d = (resp or {}).get("data") or {}
    if status == 200 and (resp or {}).get("status") == "success" and str(d.get("status", "")).lower() == "success":
        try:
            amount_ok = abs(float(d.get("amount", 0)) * 100 - o["amount_minor"]) < 1
        except (TypeError, ValueError):
            amount_ok = False
        if amount_ok and str(d.get("currency", "ETB")).upper() == "ETB":
            return finish_online(conn, o, "Chapa")
        return fail_order(conn, o, "Amount or currency mismatch")
    if str(d.get("status", "")).lower() == "failed":
        return fail_order(conn, o, "Payment failed")
    return "pending"


def verify_with_stripe(conn, o):
    if not o["provider_ref"]:
        return "pending"
    st, resp = stripe_request("GET", "/v1/checkout/sessions/" + urllib.parse.quote(o["provider_ref"]))
    if st != 200 or not resp:
        return "pending"
    if resp.get("payment_status") == "paid":
        if resp.get("amount_total") == o["amount_minor"] and str(resp.get("currency", "")).upper() == o["currency"]:
            return finish_online(conn, o, "Stripe")
        return fail_order(conn, o, "Amount or currency mismatch")
    if resp.get("status") == "expired":
        return fail_order(conn, o, "Checkout expired")
    return "pending"


def verify_with_paypal(conn, o):
    if not o["provider_ref"]:
        return "pending"
    path = "/v2/checkout/orders/" + urllib.parse.quote(o["provider_ref"])
    st, resp = paypal_request("GET", path)
    if st != 200 or not resp:
        return "pending"
    if resp.get("status") == "APPROVED":                       # buyer approved -> capture the money now
        st, resp = paypal_request("POST", path + "/capture")
        if st not in (200, 201) or not resp:
            st, resp = paypal_request("GET", path)
    if (resp or {}).get("status") == "COMPLETED":
        try:
            cap = resp["purchase_units"][0]["payments"]["captures"][0]["amount"]
            ok = abs(float(cap["value"]) * 100 - o["amount_minor"]) < 1 and cap["currency_code"] == o["currency"]
        except (KeyError, IndexError, TypeError, ValueError):
            ok = False
        return finish_online(conn, o, "PayPal") if ok else fail_order(conn, o, "Amount or currency mismatch")
    return "pending"


def verify_online(conn, o):
    return {"chapa": verify_with_chapa, "stripe": verify_with_stripe, "paypal": verify_with_paypal}[o["provider"]](conn, o)


def gateway_ready(provider):
    return {"chapa": bool(chapa_key()), "stripe": bool(stripe_key()), "paypal": paypal_ready()}.get(provider, False)


@bp.route("/api/orders/<ref>/verify", methods=["POST"])
@rate_limit(20, 60)
def order_verify(ref):
    with db() as conn:
        o, m = get_order(conn, ref)
        if o is None:
            return error("Order not found", 404)
        if o["provider"] in ONLINE_KINDS and o["status"] in ("pending", "failed"):
            if not gateway_ready(o["provider"]):
                return error("This payment method is not configured on the server", 503)
            verify_online(conn, o)
            o, m = get_order(conn, ref)
        return jsonify(order_public(o, m))


@bp.route("/api/chapa/callback", methods=["GET", "POST"])
def chapa_callback():
    """Chapa calls this after payment (needs HPF_PUBLIC_URL). We still verify with Chapa ourselves."""
    body = request.get_json(silent=True) or {}
    ref = request.args.get("trx_ref") or request.args.get("tx_ref") or body.get("tx_ref") or body.get("trx_ref") or ""
    with db() as conn:
        o, _m = get_order(conn, ref)
        if o is not None and o["provider"] == "chapa" and o["status"] in ("pending", "failed") and chapa_key():
            verify_with_chapa(conn, o)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ admin: orders
@bp.route("/api/admin/orders")
@admin_required
def admin_orders():
    with db() as conn:
        rows = conn.execute(
            "SELECT o.*, m.name AS member_name, m.email AS member_email, "
            "(SELECT COUNT(*) FROM orders o2 WHERE o2.tx_ref = o.tx_ref AND o2.id != o.id AND o.tx_ref != '') AS dup "
            "FROM orders o JOIN members m ON m.id = o.member_id ORDER BY "
            "CASE o.status WHEN 'submitted' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, o.id DESC LIMIT 300").fetchall()
    return jsonify([{"id": r["id"], "ref": r["ref"], "member": r["member_name"], "email": r["member_email"],
                     "plan": r["plan"], "method": r["method_label"], "provider": r["provider"],
                     "amountMinor": r["amount_minor"], "currency": r["currency"], "status": r["status"],
                     "txRef": r["tx_ref"] or "", "hasProof": bool(r["proof_file"]), "proofName": r["proof_name"] or "",
                     "note": r["note"] or "", "duplicateTx": r["dup"] > 0, "createdAt": r["created_at"],
                     "paidAt": r["paid_at"]} for r in rows])


@bp.route("/api/admin/orders/<int:oid>/approve", methods=["POST"])
@admin_required
def admin_approve(oid):
    with db() as conn:
        o = conn.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
        if o is None:
            return error("Order not found", 404)
        mark_paid(conn, o, "Approved by admin")
    return jsonify({"ok": True})


@bp.route("/api/admin/orders/<int:oid>/reject", methods=["POST"])
@admin_required
def admin_reject(oid):
    note = text((request.get_json(silent=True) or {}).get("note"), 300) or "Payment could not be verified"
    with db() as conn:
        conn.execute("UPDATE orders SET status='rejected', note=?, updated_at=? WHERE id=? AND status != 'paid'",
                     (note, utcnow(), oid))
    return jsonify({"ok": True})


@bp.route("/api/admin/orders/<int:oid>/proof")
@admin_required
def admin_proof(oid):
    with db() as conn:
        o = conn.execute("SELECT proof_file, proof_name FROM orders WHERE id = ?", (oid,)).fetchone()
    if not o or not o["proof_file"]:
        return error("No proof uploaded", 404)
    return send_from_directory(PROOF_DIR, o["proof_file"], as_attachment=False, download_name=o["proof_name"])


# ------------------------------------------------------------------ admin: plans, methods, members
@bp.route("/api/admin/payments/config")
@admin_required
def admin_pay_config():
    with db() as conn:
        approval = req_approval(conn)
    return jsonify({"chapaConfigured": bool(chapa_key()), "stripeConfigured": bool(stripe_key()), "paypalConfigured": paypal_ready(),
                    "paypalMode": "live" if os.environ.get("PAYPAL_MODE", "").lower() == "live" else "sandbox",
                    "publicUrl": os.environ.get("HPF_PUBLIC_URL", ""), "onlineRequiresApproval": approval})


@bp.route("/api/admin/payments/settings", methods=["PUT"])
@admin_required
def admin_pay_settings():
    d = request.get_json(silent=True) or {}
    with db() as conn:
        set_setting(conn, "online_requires_approval", "1" if d.get("onlineRequiresApproval") else "0")
    return jsonify({"ok": True})


@bp.route("/api/admin/plans")
@admin_required
def admin_plans():
    with db() as conn:
        rows = conn.execute("SELECT * FROM plans ORDER BY sort, key").fetchall()
    return jsonify([plan_dict(r) for r in rows])


def plan_vals(d):
    name = text(d.get("name"), 60)
    price = d.get("priceEtb")
    if not name or not isinstance(price, int) or isinstance(price, bool) or price < 0 or price > 1000000:
        return None
    days = d.get("periodDays") if isinstance(d.get("periodDays"), int) else 30
    def amt(k):
        v = d.get(k)
        return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1000000 else 0
    return (name, price, amt("priceUsd"), amt("priceEur"), max(0, min(days, 3650)), text(d.get("benefits"), 400),
            1 if d.get("custom") else 0, 0 if d.get("active") is False else 1)


@bp.route("/api/admin/plans", methods=["POST"])
@admin_required
def admin_plan_create():
    d = request.get_json(silent=True) or {}
    key = re.sub(r"[^a-z0-9-]", "", text(d.get("key"), 30).lower())
    vals = plan_vals(d)
    if not key or vals is None:
        return error("Key, name and a valid price are required")
    with db() as conn:
        if conn.execute("SELECT 1 FROM plans WHERE key = ?", (key,)).fetchone():
            return error("A plan with this key already exists")
        conn.execute("INSERT INTO plans (key,name,price_etb,price_usd,price_eur,period_days,benefits,custom,active,sort) VALUES (?,?,?,?,?,?,?,?,?,99)",
                     (key,) + vals)
    return jsonify({"ok": True}), 201


@bp.route("/api/admin/plans/<key>", methods=["PUT"])
@admin_required
def admin_plan_update(key):
    vals = plan_vals(request.get_json(silent=True) or {})
    if vals is None:
        return error("Name and a valid price are required")
    if key == "reader":
        vals = (vals[0], 0, 0, 0) + vals[4:7] + (1,)   # Reader stays free & active
    with db() as conn:
        conn.execute("UPDATE plans SET name=?, price_etb=?, price_usd=?, price_eur=?, period_days=?, benefits=?, custom=?, active=? WHERE key=?",
                     vals + (key,))
    return jsonify({"ok": True})


def method_vals(d):
    kind = text(d.get("kind"), 20).lower()
    label = text(d.get("label"), 120)
    if kind not in MANUAL_KINDS + ONLINE_KINDS or not label:
        return None
    cur = d.get("currencies")
    cur = [c for c in (cur if isinstance(cur, list) else []) if c in CURRENCIES] or ["ETB"]
    return (kind, label, text(d.get("accountName"), 120), text(d.get("accountNumber"), 80),
            text(d.get("instructions"), 500), 1 if d.get("enabled") else 0, ",".join(cur), safe_url(d.get("payLink")))


@bp.route("/api/admin/payment-methods")
@admin_required
def admin_methods():
    with db() as conn:
        rows = conn.execute("SELECT * FROM payment_methods ORDER BY sort, id").fetchall()
    return jsonify([{**method_public(m), "enabled": bool(m["enabled"]), "available": method_available(m)} for m in rows])


@bp.route("/api/admin/payment-methods", methods=["POST"])
@admin_required
def admin_method_create():
    vals = method_vals(request.get_json(silent=True) or {})
    if vals is None:
        return error("Kind and label are required")
    with db() as conn:
        conn.execute("INSERT INTO payment_methods (kind,label,account_name,account_number,instructions,enabled,currencies,pay_link,sort) "
                     "VALUES (?,?,?,?,?,?,?,?,99)", vals)
        mid = conn.execute("SELECT last_insert_rowid() r").fetchone()["r"]
    return jsonify({"ok": True, "id": mid}), 201


@bp.route("/api/admin/payment-methods/<int:mid>", methods=["PUT"])
@admin_required
def admin_method_update(mid):
    vals = method_vals(request.get_json(silent=True) or {})
    if vals is None:
        return error("Kind and label are required")
    with db() as conn:
        conn.execute("UPDATE payment_methods SET kind=?,label=?,account_name=?,account_number=?,instructions=?,enabled=?,currencies=?,pay_link=? WHERE id=?",
                     vals + (mid,))
    return jsonify({"ok": True})


@bp.route("/api/admin/payment-methods/<int:mid>", methods=["DELETE"])
@admin_required
def admin_method_delete(mid):
    with db() as conn:
        conn.execute("DELETE FROM payment_methods WHERE id = ?", (mid,))
    return jsonify({"ok": True})


@bp.route("/api/admin/members/<int:mid>", methods=["PUT"])
@admin_required
def admin_member_update(mid):
    d = request.get_json(silent=True) or {}
    with db() as conn:
        m = conn.execute("SELECT * FROM members WHERE id = ?", (mid,)).fetchone()
        if m is None:
            return error("Member not found", 404)
        if d.get("status") in ("active", "inactive"):
            conn.execute("UPDATE members SET status = ? WHERE id = ?", (d["status"], mid))
        plan = text(d.get("plan"), 30).lower()
        if plan and conn.execute("SELECT 1 FROM plans WHERE key = ?", (plan,)).fetchone():
            conn.execute("UPDATE members SET plan = ?, tier = ? WHERE id = ?", (plan, plan, mid))
        days = d.get("extendDays")
        if isinstance(days, int) and 0 < days <= 3650:
            activate_member(conn, mid, plan or m["plan"], days)
        if d.get("newCode"):
            conn.execute("UPDATE members SET access_code = ? WHERE id = ?", (rand(4) + "-" + rand(4), mid))
    return jsonify({"ok": True})


@bp.route("/api/admin/payment-methods/<int:mid>/qr", methods=["POST"])
@admin_required
def admin_method_qr(mid):
    """Upload a QR-code image (Alipay, Payoneer, Telebirr ...) shown to payers on the payment page."""
    from content import drop_media, save_image
    f = request.files.get("file")
    if f is None or not f.filename:
        return error("Choose a QR image")
    url, err = save_image(f)
    if err:
        return error(err)
    with db() as conn:
        r = conn.execute("SELECT qr_url FROM payment_methods WHERE id = ?", (mid,)).fetchone()
        if r is None:
            drop_media(url)
            return error("Method not found", 404)
        drop_media(r["qr_url"])
        conn.execute("UPDATE payment_methods SET qr_url = ? WHERE id = ?", (url, mid))
    return jsonify({"qrUrl": url})


@bp.route("/api/admin/payment-methods/<int:mid>/qr", methods=["DELETE"])
@admin_required
def admin_method_qr_delete(mid):
    from content import drop_media
    with db() as conn:
        r = conn.execute("SELECT qr_url FROM payment_methods WHERE id = ?", (mid,)).fetchone()
        if r:
            drop_media(r["qr_url"])
            conn.execute("UPDATE payment_methods SET qr_url = '' WHERE id = ?", (mid,))
    return jsonify({"ok": True})
