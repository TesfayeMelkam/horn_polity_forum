"""Shared helpers for all blueprints."""
import os
import re
import time
from datetime import datetime, timezone
from functools import wraps

from flask import jsonify, request, session

from database import db, utcnow

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LEVELS = {"public": 0, "member": 1, "premium": 2}
ACCESS_VALUES = ("public", "members", "premium")
_ACCESS_TO_LEVEL = {"public": "public", "members": "member", "premium": "premium"}


def load_env(base_dir):
    """Tiny .env loader (no extra package needed). Lines: KEY=value"""
    path = os.path.join(base_dir, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def error(msg, status=400):
    return jsonify({"error": msg}), status


def text(value, max_len):
    return value.strip()[:max_len] if isinstance(value, str) else ""


def valid_email(e):
    return isinstance(e, str) and 0 < len(e) <= 254 and bool(EMAIL_RE.match(e))


def safe_url(u):
    """Only http(s) links are allowed (blocks javascript: URLs)."""
    u = text(u, 300)
    return u if re.match(r"^https?://", u, re.I) else ""


_hits = {}


def rate_limit(limit, window):
    """Tiny in-memory limiter: `limit` calls per `window` seconds per IP and endpoint."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **k):
            key, now = (fn.__name__, request.remote_addr), time.time()
            recent = [t for t in _hits.get(key, []) if now - t < window]
            if len(recent) >= limit:
                return error("Too many requests - please slow down.", 429)
            recent.append(now)
            _hits[key] = recent
            return fn(*a, **k)
        return wrapper
    return deco


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **k):
        if not session.get("admin"):
            return error("Admin login required", 401)
        if request.method != "GET" and request.headers.get("X-Requested-With") != "fetch":
            return error("Bad request", 400)  # CSRF defence
        return fn(*a, **k)
    return wrapper


def member_is_active(m):
    return bool(m) and m["status"] == "active" and (not m["expires_at"] or m["expires_at"] > utcnow())


def viewer_level():
    """'premium' (admin or paid active member) / 'member' (free active member) / 'public'."""
    if session.get("admin"):
        return "premium"
    mid = session.get("member_id")
    if not mid:
        return "public"
    with db() as conn:
        m = conn.execute("SELECT plan, status, expires_at FROM members WHERE id = ?", (mid,)).fetchone()
    if not member_is_active(m):
        return "public"
    return "member" if (m["plan"] or "reader") == "reader" else "premium"


def can_access(access):
    return LEVELS[viewer_level()] >= LEVELS[_ACCESS_TO_LEVEL.get(access, "public")]


def parse_utc(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
