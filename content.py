"""Documents library, events (with RSVP), contact messages and site settings."""
import re
import secrets
import sqlite3
from datetime import datetime

from flask import Blueprint, Response, jsonify, redirect, request, send_from_directory
from werkzeug.utils import secure_filename

from common import (ACCESS_VALUES, admin_required, can_access, error, rate_limit, safe_url, text, valid_email)
from database import DOC_DIR, MEDIA_DIR, db, get_setting, set_setting, utcnow

bp = Blueprint("content", __name__)

DOC_EXT = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "csv", "txt", "rtf", "odt", "zip", "png", "jpg", "jpeg"}
IMG_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
NUM_KEYS = {"slider_height": (240, 800, 520), "slider_speed": (3, 15, 6)}
SITE_KEYS = (["announcement", "about", "contact_email", "contact_phone", "contact_address", "telegram", "slider_height", "slider_speed"]
             + [f"{k}_{l}" for k in ("announcement", "about") for l in ("am", "om", "ar")])


# ------------------------------------------------------------------ documents
def doc_dict(r):
    return {
        "id": r["id"], "title": r["title"], "description": r["description"], "category": r["category"],
        "access": r["access"], "ext": r["ext"], "size": r["size"], "downloads": r["downloads"], "isLink": r["ext"] == "link",
        "articleId": r["article_id"], "articleTitle": r["article_title"] if "article_title" in r.keys() else None,
        "createdAt": r["created_at"], "locked": not can_access(r["access"]),
    }


DOC_SELECT = ("SELECT d.*, a.title AS article_title FROM documents d "
              "LEFT JOIN articles a ON a.id = d.article_id")


def docs_for_article(conn, article_id):
    rows = conn.execute(DOC_SELECT + " WHERE d.article_id = ? ORDER BY d.id", (article_id,)).fetchall()
    return [doc_dict(r) for r in rows]


@bp.route("/api/documents")
def list_documents():
    q = (request.args.get("q") or "").strip().lower()
    cat = (request.args.get("category") or "").strip().lower()
    with db() as conn:
        rows = conn.execute(DOC_SELECT + " ORDER BY d.id DESC").fetchall()
    cats = sorted({r["category"] for r in rows})
    if cat:
        rows = [r for r in rows if r["category"].lower() == cat]
    if q:
        rows = [r for r in rows if q in (r["title"] + " " + r["description"] + " " + r["category"]).lower()]
    return jsonify({"items": [doc_dict(r) for r in rows], "categories": cats})


@bp.route("/files/<int:did>")
def download(did):
    with db() as conn:
        r = conn.execute("SELECT * FROM documents WHERE id = ?", (did,)).fetchone()
        if r is None:
            return Response("File not found", 404)
        if not can_access(r["access"]):
            return Response("This document is for members. Please sign in or join at /#/membership", 403)
        conn.execute("UPDATE documents SET downloads = downloads + 1 WHERE id = ?", (did,))
    inline = request.args.get("inline") == "1" and r["ext"] in ("pdf", "png", "jpg", "jpeg")
    return send_from_directory(DOC_DIR, r["stored_name"], as_attachment=not inline,
                               download_name=r["original_name"])


@bp.route("/go/<int:did>")
def go_link(did):
    """External source: access-checked, counted, then redirected (the URL is never exposed to people without access)."""
    with db() as conn:
        r = conn.execute("SELECT * FROM documents WHERE id = ? AND ext = 'link'", (did,)).fetchone()
        if r is None:
            return Response("Link not found", 404)
        if not can_access(r["access"]):
            return Response("This source is for members. Please sign in or join at /#/membership", 403)
        conn.execute("UPDATE documents SET downloads = downloads + 1 WHERE id = ?", (did,))
    url = safe_url(r["url"])
    return redirect(url, 302) if url else Response("Invalid link", 400)


def save_upload(f, folder, allowed):
    name = secure_filename(f.filename or "")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in allowed:
        return None, None, None, "File type not allowed (" + ", ".join(sorted(allowed)) + ")"
    stored = secrets.token_hex(12) + "." + ext
    f.save(str(folder / stored))
    return stored, name or ("file." + ext), ext, None


def doc_fields(form):
    access = form.get("access")
    art = form.get("article_id", type=int) if hasattr(form, "get") else None
    return (text(form.get("title"), 200), text(form.get("description"), 600),
            text(form.get("category"), 50) or "General", access if access in ACCESS_VALUES else "public", art or None)


@bp.route("/api/admin/documents", methods=["GET"])
@admin_required
def admin_documents():
    with db() as conn:
        rows = conn.execute(DOC_SELECT + " ORDER BY d.id DESC").fetchall()
    return jsonify([{**doc_dict(r), "url": r["url"]} for r in rows])


@bp.route("/api/admin/documents", methods=["POST"])
@admin_required
def admin_upload_document():
    title, desc, cat, access, art = doc_fields(request.form)
    link = safe_url(request.form.get("url"))
    f = request.files.get("file")
    with db() as conn:
        if art and conn.execute("SELECT 1 FROM articles WHERE id = ?", (art,)).fetchone() is None:
            art = None
        if f is None or not f.filename:                       # no file -> an external web source
            if not link:
                return error("Choose a file to upload, or enter a web link starting with http:// or https://")
            if not title:
                return error("Please give the link a title")
            did = conn.execute(
                "INSERT INTO documents (title,description,category,access,stored_name,original_name,ext,size,article_id,url,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (title, desc, cat, access, "", "", "link", 0, art, link, utcnow())).lastrowid
        else:
            stored, original, ext, err = save_upload(f, DOC_DIR, DOC_EXT)
            if err:
                return error(err)
            size = (DOC_DIR / stored).stat().st_size
            did = conn.execute(
                "INSERT INTO documents (title,description,category,access,stored_name,original_name,ext,size,article_id,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)", (title or original, desc, cat, access, stored, original, ext, size, art, utcnow())).lastrowid
        row = conn.execute(DOC_SELECT + " WHERE d.id = ?", (did,)).fetchone()
        return jsonify(doc_dict(row)), 201


@bp.route("/api/admin/documents/<int:did>", methods=["PUT"])
@admin_required
def admin_update_document(did):
    data = request.get_json(silent=True) or {}
    access = data.get("access") if data.get("access") in ACCESS_VALUES else "public"
    art = data.get("articleId") if isinstance(data.get("articleId"), int) else None
    with db() as conn:
        if conn.execute("SELECT 1 FROM documents WHERE id = ?", (did,)).fetchone() is None:
            return error("Document not found", 404)
        if art and conn.execute("SELECT 1 FROM articles WHERE id = ?", (art,)).fetchone() is None:
            art = None
        conn.execute("UPDATE documents SET title=?, description=?, category=?, access=?, article_id=? WHERE id=?",
                     (text(data.get("title"), 200) or "Untitled", text(data.get("description"), 600),
                      text(data.get("category"), 50) or "General", access, art, did))
        if data.get("url") is not None:
            conn.execute("UPDATE documents SET url = ? WHERE id = ? AND ext = 'link'", (safe_url(data.get("url")), did))
        row = conn.execute(DOC_SELECT + " WHERE d.id = ?", (did,)).fetchone()
        return jsonify(doc_dict(row))


@bp.route("/api/admin/documents/<int:did>", methods=["DELETE"])
@admin_required
def admin_delete_document(did):
    with db() as conn:
        r = conn.execute("SELECT stored_name FROM documents WHERE id = ?", (did,)).fetchone()
        if r:
            if r["stored_name"]:
                try:
                    (DOC_DIR / r["stored_name"]).unlink()
                except OSError:
                    pass
            conn.execute("DELETE FROM documents WHERE id = ?", (did,))
    return jsonify({"ok": True})


# ------------------------------------------------------------------ events
def event_dict(r, admin=False):
    d = {"id": r["id"], "title": r["title"], "startsAt": r["starts_at"], "endsAt": r["ends_at"],
         "location": r["location"], "onlineUrl": r["online_url"], "description": r["description"],
         "published": bool(r["published"]), "rsvps": r["rsvps"]}
    return d


EVENT_SELECT = "SELECT e.*, (SELECT COUNT(*) FROM event_rsvps v WHERE v.event_id = e.id) AS rsvps FROM events e"
DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


@bp.route("/api/events")
def list_events():
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    with db() as conn:
        rows = conn.execute(EVENT_SELECT + " WHERE e.published = 1 ORDER BY e.starts_at").fetchall()
    up = [event_dict(r) for r in rows if r["starts_at"] >= now]
    past = [event_dict(r) for r in rows if r["starts_at"] < now][::-1]
    return jsonify({"upcoming": up, "past": past})


@bp.route("/api/events/<int:eid>/rsvp", methods=["POST"])
@rate_limit(8, 60)
def rsvp(eid):
    data = request.get_json(silent=True) or {}
    name, email = text(data.get("name"), 100), text(data.get("email"), 254).lower()
    if not name or not valid_email(email):
        return error("Name and a valid email are required")
    with db() as conn:
        if conn.execute("SELECT 1 FROM events WHERE id = ? AND published = 1", (eid,)).fetchone() is None:
            return error("Event not found", 404)
        try:
            conn.execute("INSERT INTO event_rsvps (event_id,name,email,created_at) VALUES (?,?,?,?)",
                         (eid, name, email, utcnow()))
            new = True
        except sqlite3.IntegrityError:
            new = False
    return jsonify({"ok": True, "new": new})


def parse_event(data):
    title, starts = text(data.get("title"), 200), text(data.get("startsAt"), 16)
    ends = text(data.get("endsAt"), 16)
    if not title:
        return None, "Title is required"
    if not DT_RE.match(starts):
        return None, "Start date/time is required"
    return (title, starts, ends if DT_RE.match(ends) else "", text(data.get("location"), 200),
            safe_url(data.get("onlineUrl")), text(data.get("description"), 2000),
            0 if data.get("published") is False else 1), None


@bp.route("/api/admin/events", methods=["GET"])
@admin_required
def admin_events():
    with db() as conn:
        rows = conn.execute(EVENT_SELECT + " ORDER BY e.starts_at DESC").fetchall()
    return jsonify([event_dict(r) for r in rows])


@bp.route("/api/admin/events", methods=["POST"])
@admin_required
def admin_create_event():
    vals, err = parse_event(request.get_json(silent=True) or {})
    if err:
        return error(err)
    with db() as conn:
        eid = conn.execute("INSERT INTO events (title,starts_at,ends_at,location,online_url,description,published,created_at)"
                           " VALUES (?,?,?,?,?,?,?,?)", vals + (utcnow(),)).lastrowid
        return jsonify(event_dict(conn.execute(EVENT_SELECT + " WHERE e.id = ?", (eid,)).fetchone())), 201


@bp.route("/api/admin/events/<int:eid>", methods=["PUT"])
@admin_required
def admin_update_event(eid):
    vals, err = parse_event(request.get_json(silent=True) or {})
    if err:
        return error(err)
    with db() as conn:
        conn.execute("UPDATE events SET title=?,starts_at=?,ends_at=?,location=?,online_url=?,description=?,published=? WHERE id=?",
                     vals + (eid,))
        row = conn.execute(EVENT_SELECT + " WHERE e.id = ?", (eid,)).fetchone()
        return jsonify(event_dict(row)) if row else error("Event not found", 404)


@bp.route("/api/admin/events/<int:eid>", methods=["DELETE"])
@admin_required
def admin_delete_event(eid):
    with db() as conn:
        conn.execute("DELETE FROM events WHERE id = ?", (eid,))
    return jsonify({"ok": True})


@bp.route("/api/admin/events/<int:eid>/rsvps")
@admin_required
def admin_rsvps(eid):
    with db() as conn:
        rows = conn.execute("SELECT name, email, created_at FROM event_rsvps WHERE event_id = ? ORDER BY id", (eid,)).fetchall()
    return jsonify([dict(r) for r in rows])


# ------------------------------------------------------------------ contact
@bp.route("/api/contact", methods=["POST"])
@rate_limit(4, 60)
def contact():
    d = request.get_json(silent=True) or {}
    name, email = text(d.get("name"), 100), text(d.get("email"), 254)
    subject, body = text(d.get("subject"), 150), text(d.get("body"), 4000)
    if not name or not body or len(body) < 5:
        return error("Please enter your name and a message")
    if not valid_email(email):
        return error("A valid email is required")
    with db() as conn:
        conn.execute("INSERT INTO contact_messages (name,email,subject,body,created_at) VALUES (?,?,?,?,?)",
                     (name, email, subject, body, utcnow()))
    return jsonify({"ok": True}), 201


@bp.route("/api/admin/messages")
@admin_required
def admin_messages():
    with db() as conn:
        rows = conn.execute("SELECT * FROM contact_messages ORDER BY id DESC LIMIT 200").fetchall()
    return jsonify([{"id": r["id"], "name": r["name"], "email": r["email"], "subject": r["subject"],
                     "body": r["body"], "read": bool(r["is_read"]), "createdAt": r["created_at"]} for r in rows])


@bp.route("/api/admin/messages/<int:mid>", methods=["PUT"])
@admin_required
def admin_message_read(mid):
    with db() as conn:
        conn.execute("UPDATE contact_messages SET is_read = 1 WHERE id = ?", (mid,))
    return jsonify({"ok": True})


@bp.route("/api/admin/messages/<int:mid>", methods=["DELETE"])
@admin_required
def admin_message_delete(mid):
    with db() as conn:
        conn.execute("DELETE FROM contact_messages WHERE id = ?", (mid,))
    return jsonify({"ok": True})


# ------------------------------------------------------------------ site settings
@bp.route("/api/site")
def site():
    with db() as conn:
        return jsonify({k: get_setting(conn, k, "") for k in SITE_KEYS})


@bp.route("/api/admin/site", methods=["PUT"])
@admin_required
def admin_site():
    d = request.get_json(silent=True) or {}
    with db() as conn:
        for k in SITE_KEYS:
            if k not in d:
                continue
            if k in NUM_KEYS:                       # slider size / speed: admin may increase or decrease within safe limits
                lo, hi, default = NUM_KEYS[k]
                try:
                    v = max(lo, min(hi, int(float(d[k]))))
                except (TypeError, ValueError):
                    v = default
                set_setting(conn, k, str(v))
            else:
                set_setting(conn, k, text(d[k], 8000 if k.startswith("about") else 300))
        return jsonify({k: get_setting(conn, k, "") for k in SITE_KEYS})


# ------------------------------------------------------------------ hero slides & article covers
def safe_link(u):
    u = text(u, 300)
    return u if re.match(r"^(#|/|https?://)", u) and not u.startswith("//") else ""


def slide_dict(r):
    return {"id": r["id"], "title": r["title"], "subtitle": r["subtitle"], "imageUrl": r["image_url"],
            "link": r["link"], "cta": r["cta"], "active": bool(r["active"]), "sort": r["sort"]}


def save_image(f):
    """Save an uploaded image into /media (max 6 MB). Returns (url, error)."""
    stored, _orig, _ext, err = save_upload(f, MEDIA_DIR, IMG_EXT)
    if err:
        return None, err
    if (MEDIA_DIR / stored).stat().st_size > 6 * 1024 * 1024:
        (MEDIA_DIR / stored).unlink()
        return None, "Image is too large (max 6 MB)"
    return "/media/" + stored, None


def drop_media(url):
    if url and url.startswith("/media/"):
        try:
            (MEDIA_DIR / url[7:]).unlink()
        except OSError:
            pass


@bp.route("/api/slides")
def public_slides():
    with db() as conn:
        rows = conn.execute("SELECT * FROM slides WHERE active = 1 ORDER BY sort, id").fetchall()
    return jsonify([slide_dict(r) for r in rows])


@bp.route("/api/admin/slides", methods=["GET"])
@admin_required
def admin_slides():
    with db() as conn:
        rows = conn.execute("SELECT * FROM slides ORDER BY sort, id").fetchall()
    return jsonify([slide_dict(r) for r in rows])


def slide_form():
    f = request.form
    return (text(f.get("title"), 140), text(f.get("subtitle"), 260), safe_link(f.get("link")), text(f.get("cta"), 40),
            0 if f.get("active") == "0" else 1, f.get("sort", type=int) or 0)


@bp.route("/api/admin/slides", methods=["POST"])
@admin_required
def admin_slide_create():
    title, sub, link, cta, active, sort = slide_form()
    if not title:
        return error("Title is required")
    url = ""
    f = request.files.get("file")
    if f is not None and f.filename:
        url, err = save_image(f)
        if err:
            return error(err)
    with db() as conn:
        sid = conn.execute("INSERT INTO slides (title,subtitle,image_url,link,cta,active,sort) VALUES (?,?,?,?,?,?,?)",
                           (title, sub, url, link, cta, active, sort)).lastrowid
        return jsonify(slide_dict(conn.execute("SELECT * FROM slides WHERE id = ?", (sid,)).fetchone())), 201


@bp.route("/api/admin/slides/<int:sid>", methods=["PUT"])
@admin_required
def admin_slide_update(sid):
    title, sub, link, cta, active, sort = slide_form()
    if not title:
        return error("Title is required")
    with db() as conn:
        r = conn.execute("SELECT * FROM slides WHERE id = ?", (sid,)).fetchone()
        if r is None:
            return error("Slide not found", 404)
        url = r["image_url"]
        f = request.files.get("file")
        if f is not None and f.filename:
            new, err = save_image(f)
            if err:
                return error(err)
            drop_media(url)
            url = new
        elif request.form.get("remove_image") == "1":
            drop_media(url)
            url = ""
        conn.execute("UPDATE slides SET title=?,subtitle=?,image_url=?,link=?,cta=?,active=?,sort=? WHERE id=?",
                     (title, sub, url, link, cta, active, sort, sid))
        return jsonify(slide_dict(conn.execute("SELECT * FROM slides WHERE id = ?", (sid,)).fetchone()))


@bp.route("/api/admin/slides/<int:sid>", methods=["DELETE"])
@admin_required
def admin_slide_delete(sid):
    with db() as conn:
        r = conn.execute("SELECT image_url FROM slides WHERE id = ?", (sid,)).fetchone()
        if r:
            drop_media(r["image_url"])
            conn.execute("DELETE FROM slides WHERE id = ?", (sid,))
    return jsonify({"ok": True})


@bp.route("/api/admin/articles/<int:aid>/cover", methods=["POST"])
@admin_required
def admin_cover_upload(aid):
    f = request.files.get("file")
    if f is None or not f.filename:
        return error("Choose an image")
    url, err = save_image(f)
    if err:
        return error(err)
    with db() as conn:
        r = conn.execute("SELECT cover FROM articles WHERE id = ?", (aid,)).fetchone()
        if r is None:
            drop_media(url)
            return error("Article not found", 404)
        drop_media(r["cover"])
        conn.execute("UPDATE articles SET cover = ? WHERE id = ?", (url, aid))
    return jsonify({"cover": url})


@bp.route("/api/admin/articles/<int:aid>/cover", methods=["DELETE"])
@admin_required
def admin_cover_delete(aid):
    with db() as conn:
        r = conn.execute("SELECT cover FROM articles WHERE id = ?", (aid,)).fetchone()
        if r:
            drop_media(r["cover"])
            conn.execute("UPDATE articles SET cover = '' WHERE id = ?", (aid,))
    return jsonify({"ok": True})
