"""Horn Polity Forum v4 - Flask backend.

PyCharm: right-click this file > Run 'app', then open the URL printed in the console.
Admin panel: /admin   (default password: admin123  - change it with HPF_ADMIN_PASSWORD
or from the admin Settings tab).
"""
import ensure_deps  # noqa: F401  (installs Flask automatically if it is missing)
import csv
import io
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
import webbrowser
from functools import wraps
from xml.sax.saxutils import escape as xesc

from flask import (Flask, Response, jsonify, redirect, request,
                   send_from_directory, session)
from werkzeug.security import check_password_hash, generate_password_hash

from common import (ACCESS_VALUES, admin_required, can_access, error, load_env, rate_limit, text, valid_email)
from content import docs_for_article
LANGS = ("en", "am", "om", "ar")
from database import (MEDIA_DIR, db, get_setting, init_db, set_setting, unique_slug, utcnow)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

load_env(BASE_DIR)
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.url_map.strict_slashes = False   # /admin and /admin/ both work


def load_secret_key():
    env = os.environ.get("HPF_SECRET_KEY")
    if env:
        return env
    path = os.path.join(BASE_DIR, ".secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


app.secret_key = load_secret_key()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  MAX_CONTENT_LENGTH=20 * 1024 * 1024)

DEFAULT_ADMIN_PASSWORD = "admin123"


def bootstrap():
    init_db()
    with db() as conn:
        if get_setting(conn, "admin_pw_hash") is None:
            pw = os.environ.get("HPF_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
            set_setting(conn, "admin_pw_hash", generate_password_hash(pw))
            if pw == DEFAULT_ADMIN_PASSWORD:
                print("  [!] Admin password is the default 'admin123' - change it in /admin > Settings.")


bootstrap()

@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' "
        "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:")
    return resp


ARTICLE_SELECT = ("SELECT a.*, (SELECT COUNT(*) FROM comments c WHERE c.article_id = a.id) "
                  "AS comment_count FROM articles a")


def tag_list(row):
    return [t.strip() for t in (row["tags"] or "").split(",") if t.strip()]


def first_part(body, limit=420):
    para = body.strip().split("\n\n")[0]
    return para[:limit] + ("…" if len(para) > limit else "")


def article_dict(row, full=False):
    words = len(re.findall(r"\w+", row["body"]))
    access = row["access"] if "access" in row.keys() else "public"
    d = {
        "id": row["id"], "slug": row["slug"], "title": row["title"],
        "category": row["category"], "tags": tag_list(row), "excerpt": row["excerpt"] or "",
        "author": row["author"], "featured": bool(row["featured"]), "access": access,
        "cover": row["cover"] if "cover" in row.keys() else "", "lang": row["lang"] if "lang" in row.keys() else "en",
        "published": bool(row["published"]), "views": row["views"], "likes": row["likes"],
        "commentCount": row["comment_count"], "readingMinutes": max(1, round(words / 200)),
        "publishedAt": row["published_at"], "updatedAt": row["updated_at"],
    }
    if full:
        ok = can_access(access)
        d["locked"] = not ok
        d["body"] = row["body"] if ok else first_part(row["body"])
    return d


def comment_dict(row):
    # email is never exposed publicly
    return {"id": row["id"], "name": row["name"], "body": row["body"], "createdAt": row["created_at"]}


def relevance(row, terms):
    """Simple weighted keyword score. Every term must match somewhere."""
    fields = [(row["title"], 5), (row["tags"], 3), (row["excerpt"], 2), (row["body"], 1),
              (row["category"], 2)]
    total = 0
    for t in terms:
        s = sum(w for f, w in fields if f and t in f.lower())
        if s == 0:
            return 0
        total += s
    return total


# ------------------------------------------------------------------ pages
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/admin")
@app.route("/admin.html")
@app.route("/admin/index.html")
@app.route("/static/admin.html")
def admin_page():
    return send_from_directory(STATIC_DIR, "admin.html")


@app.route("/pay/<ref>")
def pay_page(ref):
    # Return URL from payment gateways; the front-end reads the path.
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/index.html")
@app.route("/static/index.html")
def index_redirect():
    return redirect("/", code=302)


@app.route("/sw.js")
def service_worker():
    resp = send_from_directory(STATIC_DIR, "sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(STATIC_DIR, "manifest.webmanifest", mimetype="application/manifest+json")


@app.route("/media/<name>")
def media(name):
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
        return Response("Not found", 404)
    resp = send_from_directory(MEDIA_DIR, name)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /admin\nDisallow: /api/admin\n", mimetype="text/plain")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "3.0"})


# ------------------------------------------------------------------ public API
@app.route("/api/articles")
def list_articles():
    q = (request.args.get("q") or "").strip().lower()
    category = (request.args.get("category") or "").strip().lower()
    tag = (request.args.get("tag") or "").strip().lower()
    sort = request.args.get("sort", "new")
    page = max(request.args.get("page", 1, type=int), 1)
    per = min(max(request.args.get("per", 6, type=int), 1), 24)
    slugs = [s for s in (request.args.get("slugs") or "").split(",") if s]
    lang = (request.args.get("lang") or "").strip().lower()

    with db() as conn:
        rows = conn.execute(ARTICLE_SELECT + " WHERE a.published = 1").fetchall()

    if category:
        rows = [r for r in rows if r["category"].lower() == category]
    if tag:
        rows = [r for r in rows if tag in [t.lower() for t in tag_list(r)]]
    if slugs:
        rows = [r for r in rows if r["slug"] in slugs]
    if lang in LANGS:
        rows = [r for r in rows if r["lang"] == lang]

    if q:
        terms = q.split()
        scored = [(relevance(r, terms), r) for r in rows]
        scored = [(s, r) for s, r in scored if s > 0]
        scored.sort(key=lambda x: (x[0], x[1]["published_at"]), reverse=True)
        rows = [r for _, r in scored]
    elif sort == "popular":
        rows.sort(key=lambda r: r["views"] + 3 * r["likes"] + 5 * r["comment_count"], reverse=True)
    else:
        rows.sort(key=lambda r: (r["published_at"], r["id"]), reverse=True)

    total = len(rows)
    pages = max(1, -(-total // per))
    chunk = rows[(page - 1) * per: page * per]
    return jsonify({"items": [article_dict(r) for r in chunk], "total": total,
                    "page": page, "pages": pages})


@app.route("/api/articles/<slug>")
def get_article(slug):
    with db() as conn:
        row = conn.execute(ARTICLE_SELECT + " WHERE a.slug = ? AND a.published = 1", (slug,)).fetchone()
        if row is None:
            return error("Article not found", 404)
        viewed = session.get("viewed", [])
        if row["id"] not in viewed:
            conn.execute("UPDATE articles SET views = views + 1 WHERE id = ?", (row["id"],))
            session["viewed"] = (viewed + [row["id"]])[-50:]
            row = conn.execute(ARTICLE_SELECT + " WHERE a.id = ?", (row["id"],)).fetchone()
        others = conn.execute(ARTICLE_SELECT + " WHERE a.published = 1 AND a.id != ?", (row["id"],)).fetchall()

    mine = {t.lower() for t in tag_list(row)}

    def sim(r):
        return 2 * len(mine & {t.lower() for t in tag_list(r)}) + (1 if r["category"] == row["category"] else 0)

    related = sorted(others, key=lambda r: (sim(r), r["views"]), reverse=True)
    related = [r for r in related if sim(r) > 0][:3]
    data = article_dict(row, full=True)
    data["related"] = [article_dict(r) for r in related]
    with db() as conn:
        data["documents"] = docs_for_article(conn, row["id"])
    return jsonify(data)


@app.route("/api/articles/<slug>/like", methods=["POST"])
@rate_limit(30, 60)
def like_article(slug):
    delta = 1 if (request.get_json(silent=True) or {}).get("delta", 1) >= 0 else -1
    with db() as conn:
        row = conn.execute("SELECT id FROM articles WHERE slug = ? AND published = 1", (slug,)).fetchone()
        if row is None:
            return error("Article not found", 404)
        conn.execute("UPDATE articles SET likes = MAX(0, likes + ?) WHERE id = ?", (delta, row["id"]))
        likes = conn.execute("SELECT likes FROM articles WHERE id = ?", (row["id"],)).fetchone()["likes"]
    return jsonify({"likes": likes})


@app.route("/api/articles/<slug>/comments", methods=["GET"])
def get_comments(slug):
    with db() as conn:
        art = conn.execute("SELECT id FROM articles WHERE slug = ? AND published = 1", (slug,)).fetchone()
        if art is None:
            return error("Article not found", 404)
        rows = conn.execute("SELECT * FROM comments WHERE article_id = ? ORDER BY id DESC", (art["id"],)).fetchall()
    return jsonify([comment_dict(r) for r in rows])


@app.route("/api/articles/<slug>/comments", methods=["POST"])
@rate_limit(6, 60)
def post_comment(slug):
    data = request.get_json(silent=True) or {}
    name, email, body = text(data.get("name"), 80), text(data.get("email"), 254), text(data.get("body"), 3000)
    if not name or not body:
        return error("Name and comment are required")
    if len(body) < 3:
        return error("Comment is too short")
    if not valid_email(email):
        return error("A valid email is required")
    with db() as conn:
        art = conn.execute("SELECT id FROM articles WHERE slug = ? AND published = 1", (slug,)).fetchone()
        if art is None:
            return error("Article not found", 404)
        cur = conn.execute("INSERT INTO comments (article_id,name,email,body,created_at) VALUES (?,?,?,?,?)",
                           (art["id"], name, email, body, utcnow()))
        row = conn.execute("SELECT * FROM comments WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(comment_dict(row)), 201


@app.route("/api/meta")
def meta():
    with db() as conn:
        rows = conn.execute(ARTICLE_SELECT + " WHERE a.published = 1").fetchall()
    cats, tags = {}, {}
    for r in rows:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
        for t in tag_list(r):
            tags[t] = tags.get(t, 0) + 1
    newest = sorted(rows, key=lambda r: r["published_at"], reverse=True)
    trending = sorted(rows, key=lambda r: r["views"] + 3 * r["likes"] + 5 * r["comment_count"], reverse=True)[:4]
    return jsonify({
        "categories": [{"name": k, "count": v} for k, v in sorted(cats.items())],
        "tags": [{"name": k, "count": v} for k, v in sorted(tags.items(), key=lambda x: -x[1])[:14]],
        "featured": [article_dict(r) for r in newest if r["featured"]][:3],
        "trending": [article_dict(r) for r in trending],
        "stats": {"articles": len(rows), "views": sum(r["views"] for r in rows), "categories": len(cats)},
    })


@app.route("/api/suggest")
def suggest():
    """Search-as-you-type suggestions: matching article titles and tags."""
    q = (request.args.get("q") or "").strip().lower()[:60]
    if len(q) < 2:
        return jsonify([])
    with db() as conn:
        rows = conn.execute("SELECT slug, title, tags FROM articles WHERE published = 1").fetchall()
    out = [{"type": "article", "label": r["title"], "slug": r["slug"]} for r in rows if q in r["title"].lower()]
    tags = []
    for r in rows:
        for t in tag_list(r):
            if q in t.lower() and t not in tags:
                tags.append(t)
    out += [{"type": "tag", "label": t} for t in tags[:3]]
    return jsonify(out[:6])


@app.route("/api/recommend")
def recommend():
    """'For you' list from the reader's own history (sent by the browser; nothing stored)."""
    split = lambda k: [x.strip().lower() for x in (request.args.get(k) or "")[:600].split(",") if x.strip()]
    tags, cats, exclude = set(split("tags")), set(split("cats")), set(split("exclude"))
    with db() as conn:
        rows = conn.execute(ARTICLE_SELECT + " WHERE a.published = 1").fetchall()

    def score(r):
        return (3 * len(tags & {t.lower() for t in tag_list(r)})
                + (2 if r["category"].lower() in cats else 0) + min(r["views"], 500) / 500)

    ranked = sorted((r for r in rows if r["slug"] not in exclude), key=score, reverse=True)[:4]
    return jsonify([article_dict(r) for r in ranked])


@app.route("/api/newsletter", methods=["POST"])
@rate_limit(5, 60)
def newsletter():
    email = text((request.get_json(silent=True) or {}).get("email"), 254).lower()
    if not valid_email(email):
        return error("A valid email is required")
    try:
        with db() as conn:
            conn.execute("INSERT INTO subscribers (email, created_at) VALUES (?, ?)", (email, utcnow()))
        new = True
    except sqlite3.IntegrityError:
        new = False
    return jsonify({"email": email, "newSubscription": new})


@app.route("/rss.xml")
def rss():
    with db() as conn:
        rows = conn.execute("SELECT * FROM articles WHERE published = 1 ORDER BY published_at DESC LIMIT 20").fetchall()
    base = request.host_url.rstrip("/")
    items = "".join(
        f"<item><title>{xesc(r['title'])}</title><link>{base}/#/a/{r['slug']}</link>"
        f"<guid isPermaLink=\"false\">{r['slug']}</guid><description>{xesc(r['excerpt'] or '')}</description>"
        f"<pubDate>{r['published_at']}</pubDate></item>" for r in rows)
    xml = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?><rss version=\"2.0\"><channel>"
           f"<title>Horn Polity Forum</title><link>{base}</link>"
           "<description>Political science of Ethiopia and the Horn</description>" + items + "</channel></rss>")
    return Response(xml, mimetype="application/rss+xml")


# ------------------------------------------------------------------ admin API
@app.route("/api/admin/login", methods=["POST"])
@rate_limit(6, 60)
def admin_login():
    pw = (request.get_json(silent=True) or {}).get("password", "")
    with db() as conn:
        ok = isinstance(pw, str) and check_password_hash(get_setting(conn, "admin_pw_hash"), pw)
    if not ok:
        return error("Wrong password", 401)
    session["admin"] = True
    return jsonify({"ok": True})


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin", None)
    return jsonify({"ok": True})


@app.route("/api/admin/me")
def admin_me():
    return jsonify({"admin": bool(session.get("admin"))})


@app.route("/api/admin/password", methods=["POST"])
@admin_required
def admin_password():
    data = request.get_json(silent=True) or {}
    old, new = data.get("old", ""), data.get("new", "")
    if not isinstance(new, str) or len(new) < 8:
        return error("New password must be at least 8 characters")
    with db() as conn:
        if not check_password_hash(get_setting(conn, "admin_pw_hash"), old if isinstance(old, str) else ""):
            return error("Current password is wrong", 401)
        set_setting(conn, "admin_pw_hash", generate_password_hash(new))
    return jsonify({"ok": True})


@app.route("/api/admin/stats")
@admin_required
def admin_stats():
    with db() as conn:
        one = lambda q: conn.execute(q).fetchone()[0]
        stats = {
            "articles": one("SELECT COUNT(*) FROM articles WHERE published=1"),
            "drafts": one("SELECT COUNT(*) FROM articles WHERE published=0"),
            "comments": one("SELECT COUNT(*) FROM comments"),
            "subscribers": one("SELECT COUNT(*) FROM subscribers"),
            "members": one("SELECT COUNT(*) FROM members"),
            "views": one("SELECT COALESCE(SUM(views),0) FROM articles"),
            "likes": one("SELECT COALESCE(SUM(likes),0) FROM articles"),
            "revenueMinor": one("SELECT COALESCE(SUM(amount_minor),0) FROM orders WHERE status='paid'"),
            "pendingOrders": one("SELECT COUNT(*) FROM orders WHERE status='submitted'"),
            "unreadMessages": one("SELECT COUNT(*) FROM contact_messages WHERE is_read=0"),
            "documents": one("SELECT COUNT(*) FROM documents"),
            "events": one("SELECT COUNT(*) FROM events"),
        }
        top = conn.execute("SELECT title, slug, views FROM articles ORDER BY views DESC LIMIT 8").fetchall()
        recent = conn.execute("SELECT c.id, c.name, c.body, c.created_at, a.title FROM comments c "
                              "JOIN articles a ON a.id = c.article_id ORDER BY c.id DESC LIMIT 5").fetchall()
        tiers = conn.execute("SELECT plan AS tier, COUNT(*) n FROM members GROUP BY plan").fetchall()
    with db() as conn2:
        stats["revenueByCurrency"] = {r["currency"]: r["s"] for r in conn2.execute(
            "SELECT currency, SUM(amount_minor) s FROM orders WHERE status='paid' GROUP BY currency").fetchall()}
    stats["top"] = [dict(r) for r in top]
    stats["recentComments"] = [dict(r) for r in recent]
    stats["tiers"] = {r["tier"]: r["n"] for r in tiers}
    return jsonify(stats)


def parse_article(data):
    title, body = text(data.get("title"), 200), text(data.get("body"), 50000)
    if not title or not body:
        return None, "Title and body are required"
    raw_tags = data.get("tags") or ""
    if isinstance(raw_tags, list):
        raw_tags = ",".join(str(t) for t in raw_tags)
    tags = [t.strip()[:30] for t in re.split(r"[,;]", str(raw_tags)) if t.strip()][:8]
    return {
        "title": title, "body": body, "tags": ", ".join(tags),
        "category": text(data.get("category"), 50) or "Essay",
        "excerpt": text(data.get("excerpt"), 400),
        "author": text(data.get("author"), 100) or "Editorial Board",
        "featured": 1 if data.get("featured") else 0,
        "published": 0 if data.get("published") is False else 1,
        "access": data.get("access") if data.get("access") in ACCESS_VALUES else "public",
        "lang": data.get("lang") if data.get("lang") in LANGS else "en",
    }, None


@app.route("/api/admin/articles", methods=["GET"])
@admin_required
def admin_list_articles():
    with db() as conn:
        rows = conn.execute(ARTICLE_SELECT + " ORDER BY a.published_at DESC, a.id DESC").fetchall()
    return jsonify([article_dict(r, full=True) for r in rows])


@app.route("/api/admin/articles", methods=["POST"])
@admin_required
def admin_create_article():
    a, err = parse_article(request.get_json(silent=True) or {})
    if err:
        return error(err)
    now = utcnow()
    with db() as conn:
        aid = conn.execute(
            "INSERT INTO articles (slug,title,category,tags,excerpt,body,author,featured,published,access,lang,published_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (unique_slug(conn, a["title"]), a["title"], a["category"], a["tags"], a["excerpt"], a["body"],
             a["author"], a["featured"], a["published"], a["access"], a["lang"], now, now)).lastrowid
        row = conn.execute(ARTICLE_SELECT + " WHERE a.id = ?", (aid,)).fetchone()
        return jsonify(article_dict(row, full=True)), 201


@app.route("/api/admin/articles/<int:aid>", methods=["PUT"])
@admin_required
def admin_update_article(aid):
    a, err = parse_article(request.get_json(silent=True) or {})
    if err:
        return error(err)
    with db() as conn:
        if conn.execute("SELECT 1 FROM articles WHERE id = ?", (aid,)).fetchone() is None:
            return error("Article not found", 404)
        conn.execute(
            "UPDATE articles SET title=?,category=?,tags=?,excerpt=?,body=?,author=?,featured=?,published=?,"
            "access=?,lang=?,updated_at=? WHERE id=?",
            (a["title"], a["category"], a["tags"], a["excerpt"], a["body"], a["author"], a["featured"],
             a["published"], a["access"], a["lang"], utcnow(), aid))
        row = conn.execute(ARTICLE_SELECT + " WHERE a.id = ?", (aid,)).fetchone()
        return jsonify(article_dict(row, full=True))


@app.route("/api/admin/articles/<int:aid>", methods=["DELETE"])
@admin_required
def admin_delete_article(aid):
    with db() as conn:
        conn.execute("DELETE FROM articles WHERE id = ?", (aid,))
    return jsonify({"ok": True})


@app.route("/api/admin/backup")
@admin_required
def admin_backup():
    with db() as conn:
        rows = conn.execute(ARTICLE_SELECT + " ORDER BY a.id").fetchall()
    resp = jsonify([article_dict(r, full=True) for r in rows])
    resp.headers["Content-Disposition"] = "attachment; filename=hpf-articles-backup.json"
    return resp


@app.route("/api/admin/import", methods=["POST"])
@admin_required
def admin_import():
    items = request.get_json(silent=True)
    if not isinstance(items, list):
        return error("Expected a JSON list of articles")
    added = 0
    with db() as conn:
        for it in items[:200]:
            a, err = parse_article(it) if isinstance(it, dict) else (None, "bad")
            if err or conn.execute("SELECT 1 FROM articles WHERE title = ?", (a["title"],)).fetchone():
                continue
            now = utcnow()
            conn.execute(
                "INSERT INTO articles (slug,title,category,tags,excerpt,body,author,featured,published,access,lang,published_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (unique_slug(conn, a["title"]), a["title"], a["category"], a["tags"], a["excerpt"], a["body"],
                 a["author"], a["featured"], a["published"], a["access"], a["lang"], now, now))
            added += 1
    return jsonify({"added": added})


@app.route("/api/admin/comments")
@admin_required
def admin_comments():
    with db() as conn:
        rows = conn.execute("SELECT c.*, a.title FROM comments c JOIN articles a ON a.id=c.article_id "
                            "ORDER BY c.id DESC LIMIT 200").fetchall()
    return jsonify([{"id": r["id"], "name": r["name"], "email": r["email"], "body": r["body"],
                     "createdAt": r["created_at"], "article": r["title"]} for r in rows])


@app.route("/api/admin/comments/<int:cid>", methods=["DELETE"])
@admin_required
def admin_delete_comment(cid):
    with db() as conn:
        conn.execute("DELETE FROM comments WHERE id = ?", (cid,))
    return jsonify({"ok": True})


def table_response(rows, columns, fmt):
    data = [dict(r) for r in rows]
    if fmt != "csv":
        return jsonify(data)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columns)
    for r in data:
        # guard against spreadsheet formula injection
        w.writerow([("'" + str(r[c])) if str(r[c]).startswith(("=", "+", "-", "@")) else r[c] for c in columns])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=export.csv"})


@app.route("/api/admin/subscribers")
@admin_required
def admin_subscribers():
    with db() as conn:
        rows = conn.execute("SELECT id, email, created_at FROM subscribers ORDER BY id DESC").fetchall()
    return table_response(rows, ["id", "email", "created_at"], request.args.get("format"))


@app.route("/api/admin/members")
@admin_required
def admin_members():
    with db() as conn:
        rows = conn.execute("SELECT id, name, email, affiliation, plan, status, COALESCE(expires_at,'') AS expires_at, "
                            "COALESCE(access_code,'') AS access_code, created_at FROM members ORDER BY id DESC").fetchall()
    return table_response(rows, ["id", "name", "email", "affiliation", "plan", "status", "expires_at", "created_at"],
                          request.args.get("format"))


import content  # noqa: E402
import payments  # noqa: E402

app.register_blueprint(content.bp)
app.register_blueprint(payments.bp)


# ------------------------------------------------------------------ errors
NOT_FOUND_HTML = """<!doctype html><meta charset=utf-8><title>Page not found</title>
<body style="font-family:system-ui;background:#0b1020;color:#f3f4f6;display:grid;place-items:center;min-height:100vh;margin:0">
<div style="max-width:520px;padding:24px"><h1>Page not found</h1>
<p>Use these links:</p><p><a style="color:#fb923c" href="/">Home</a> &middot; <a style="color:#fb923c" href="/admin">Admin</a></p>
<p style="color:#9ca3af;font-size:14px">If <b>/admin</b> shows this page, an <b>older copy</b> of the app is still running on this port.
In PyCharm press the red Stop square (or close old Run windows), run this project again and open the exact address printed in the console.</p></div>"""


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return error("Not found", 404)
    return NOT_FOUND_HTML, 404


@app.errorhandler(405)
def bad_method(_e):
    return error("Method not allowed", 405)


@app.errorhandler(413)
def too_big(_e):
    return error("Request too large", 413)


@app.errorhandler(500)
def server_error(_e):
    return error("Internal server error", 500)


# ------------------------------------------------------------------ start
def find_free_port(preferred=8080, tries=20):
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return preferred


if __name__ == "__main__":
    preferred = int(os.environ.get("PORT", "8080"))
    port = find_free_port(preferred)
    for needed in ("index.html", "admin.html", "js/app.js", "js/admin.js", "css/style.css"):
        if not os.path.exists(os.path.join(STATIC_DIR, needed)):
            print(f"  [ERROR] Missing file static/{needed} - re-extract the zip completely.")
    if port != preferred:
        print(f"\n  [!] Port {preferred} is busy (an OLDER COPY of the app is probably still running).")
        print("      Stop old runs with the red square in PyCharm. Using the new port below.")
    print(f"\n  Horn Polity Forum  ->  http://127.0.0.1:{port}"
          f"\n  Admin panel        ->  http://127.0.0.1:{port}/admin  (default password: admin123)\n")
    if not os.environ.get("HPF_NO_BROWSER"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
