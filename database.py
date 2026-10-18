"""SQLite layer for Horn Polity Forum v2."""
import os
import re
import sqlite3
import secrets
from datetime import timedelta
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "hornpolity.db"
UPLOAD_ROOT = BASE / "uploads"
DOC_DIR = UPLOAD_ROOT / "documents"
PROOF_DIR = UPLOAD_ROOT / "proofs"
MEDIA_DIR = UPLOAD_ROOT / "media"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s or "article")[:80].strip("-")


@contextmanager
def db():
    """Commit on success, roll back on error, ALWAYS close (important on Windows)."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def unique_slug(conn, title, exclude_id=None):
    base = slugify(title)
    slug, n = base, 2
    while True:
        row = conn.execute("SELECT id FROM articles WHERE slug = ?", (slug,)).fetchone()
        if row is None or row["id"] == exclude_id:
            return slug
        slug = f"{base}-{n}"
        n += 1


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    excerpt TEXT,
    body TEXT NOT NULL,
    author TEXT NOT NULL,
    featured INTEGER NOT NULL DEFAULT 0,
    published INTEGER NOT NULL DEFAULT 1,
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    published_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    affiliation TEXT,
    tier TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    tier TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS slides (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, subtitle TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL DEFAULT '', link TEXT NOT NULL DEFAULT '', cta TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1, sort INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS plans (
    key TEXT PRIMARY KEY, name TEXT NOT NULL, price_etb INTEGER NOT NULL DEFAULT 0,
    period_days INTEGER NOT NULL DEFAULT 30, benefits TEXT NOT NULL DEFAULT '',
    custom INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, sort INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS payment_methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, label TEXT NOT NULL,
    account_name TEXT NOT NULL DEFAULT '', account_number TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 0, sort INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT NOT NULL UNIQUE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    plan TEXT NOT NULL, method_id INTEGER, provider TEXT NOT NULL, method_label TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT 'ETB', amount_minor INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    tx_ref TEXT, proof_file TEXT, proof_name TEXT, checkout_url TEXT, note TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, paid_at TEXT);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'General', access TEXT NOT NULL DEFAULT 'public',
    stored_name TEXT NOT NULL, original_name TEXT NOT NULL, ext TEXT NOT NULL, size INTEGER NOT NULL DEFAULT 0,
    downloads INTEGER NOT NULL DEFAULT 0, article_id INTEGER REFERENCES articles(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '', online_url TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '', published INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event_rsvps (
    id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    name TEXT NOT NULL, email TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(event_id, email));
CREATE TABLE IF NOT EXISTS contact_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL, subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
"""


# (title, category, tags, excerpt, body, featured, views, likes, published_at)
SEED = [
    ("Democratic Masks and Authoritarian Resilience in the Horn", "Analysis",
     "democratization, authoritarianism, institutions",
     "How regimes adopt the language of democracy while keeping the core of power intact.",
     "Across the Horn, ruling coalitions have learned that elections, constitutions and reform rhetoric can serve as instruments of control as much as of accountability.\n\n"
     "## A framework\n\nThe essay separates **genuine liberalisation** from *managed openings* by looking at three things: institutional design, security-sector loyalty and elite bargaining.\n\n"
     "> Formal institutions matter less than who is able to ignore them.\n\n"
     "- Do courts and electoral bodies have independent budgets?\n- Can opposition actors organise without permission?\n- Who controls the coercive apparatus?\n\n"
     "Reading these signals together helps readers avoid mistaking ceremony for change.",
     1, 412, 37, "2026-09-20T09:00:00Z"),
    ("Elite Co-optation and Protest Cycles in Ethiopia", "Research Note",
     "protest, elites, transition",
     "Why mass mobilisation often ends in elite reshuffling rather than structural change.",
     "Protest waves frequently open a brief window for institutional change. Yet co-optation of movement leaders, selective concessions and security pressure tend to close that window.\n\n"
     "## What to track\n\nThis note proposes indicators for telling whether concessions are **institutionalised** (written into law and budgets) or **personalised** (dependent on a single leader).\n\n"
     "Comparative cases suggest the second type rarely survives a change in leadership.",
     1, 358, 29, "2026-09-08T09:00:00Z"),
    ("Reading the Horn as a Regional Security System", "Commentary",
     "security, regionalism, red-sea",
     "Why Ethiopia, Somalia, Sudan, Eritrea, Djibouti and Kenya cannot be analysed in isolation.",
     "Security dynamics in the Horn are deeply interlinked: refugee flows, port access, Red Sea geopolitics and cross-border insurgencies bind domestic politics to regional alignments.\n\n"
     "A systems view helps explain why local settlements often unravel when regional patrons shift their priorities.",
     0, 295, 21, "2026-08-27T09:00:00Z"),
    ("Federalism and Ethnic Politics: Debates Worth Having", "Debate",
     "federalism, identity, constitution",
     "A structured look at the strongest arguments on both sides of the ethnic-federalism debate.",
     "Few topics in Ethiopian politics generate as much heat as ethnic federalism. This piece sets out the best case made by its defenders and by its critics, without taking a side.\n\n"
     "## Defenders argue\n\nSelf-administration protects language, culture and local voice.\n\n"
     "## Critics argue\n\nIdentity-based units can harden boundaries and raise the stakes of every dispute.\n\n"
     "The empirical question is under which conditions each effect dominates.",
     0, 244, 18, "2026-08-10T09:00:00Z"),
    ("Reading List: Ten Books on State Formation in Africa", "Reading List",
     "reading-list, state-formation, theory",
     "A curated starting point for students of statehood, war-making and rule in the Horn.",
     "This list pairs classic theory on state formation with regional case studies, so that readers can test general arguments against local evidence.\n\n"
     "Start with the theory, then read two cases that *disagree* with it. The friction is where the learning happens.",
     0, 190, 25, "2026-07-30T09:00:00Z"),
    ("Methods Note: Using Event Data Responsibly", "Methods",
     "methods, data, conflict-research",
     "What conflict event datasets can and cannot tell you about political violence.",
     "Event datasets are powerful but biased toward what media and monitors can see. Before trusting a trend, ask who was reporting, where, and with what access.\n\n"
     "## Quick checklist\n\n- Check coverage gaps by region and period.\n- Compare at least two sources.\n- Report uncertainty alongside every figure.",
     0, 151, 12, "2026-07-12T09:00:00Z"),
]


ADD_COLUMNS = {
    "articles": [("access", "TEXT NOT NULL DEFAULT 'public'"), ("cover", "TEXT NOT NULL DEFAULT ''"),
                 ("lang", "TEXT NOT NULL DEFAULT 'en'")],
    "plans": [("price_usd", "INTEGER NOT NULL DEFAULT 0"), ("price_eur", "INTEGER NOT NULL DEFAULT 0")],
    "payment_methods": [("currencies", "TEXT NOT NULL DEFAULT 'ETB'"), ("pay_link", "TEXT NOT NULL DEFAULT ''"),
                        ("qr_url", "TEXT NOT NULL DEFAULT ''")],
    "orders": [("provider_ref", "TEXT")],
    "documents": [("url", "TEXT NOT NULL DEFAULT ''")],
    "members": [("plan", "TEXT NOT NULL DEFAULT 'reader'"), ("status", "TEXT NOT NULL DEFAULT 'active'"),
                ("expires_at", "TEXT"), ("access_code", "TEXT")],
}

SITE_DEFAULTS = {
    "announcement": "",
    "about": ("Horn Polity Forum is an independent, research-driven platform for analysis of power, institutions "
              "and conflict in Ethiopia and the Horn of Africa.\n\n## Our mission\n\nTo make rigorous, "
              "evidence-aware political analysis accessible to students, scholars, journalists and practitioners.\n\n"
              "## What we publish\n\n- Short analytical essays and research notes\n- Structured debates\n"
              "- Reading lists, datasets and working papers in our Library\n\n"
              "> Edit this page any time in Admin > Site settings."),
    "contact_email": "", "contact_phone": "", "contact_address": "", "telegram": "",
    "announcement_am": "", "announcement_om": "", "announcement_ar": "",
    "about_am": ("ሆርን ፖሊቲ ፎረም በኢትዮጵያና በአፍሪካ ቀንድ ስላለው ሥልጣን፣ ተቋማትና ግጭት የሚተነተን ነጻ፣ በምርምር ላይ የተመሠረተ መድረክ ነው።\n\n"
                 "## ተልእኳችን\n\nጥብቅና በማስረጃ የተደገፈ የፖለቲካ ትንተናን ለተማሪዎች፣ ለምሁራን፣ ለጋዜጠኞችና ለባለሙያዎች ተደራሽ ማድረግ።\n\n"
                 "## የምናትመው\n\n- አጫጭር ትንተናዊ ጽሑፎችና የምርምር ማስታወሻዎች\n- የተዋቀሩ ክርክሮች\n- በቤተ መጻሕፍታችን ውስጥ የንባብ ዝርዝሮች፣ መረጃዎችና የሥራ ወረቀቶች"),
    "about_om": ("Horn Polity Forum waltajjii ofiin of danda'u, qorannoo irratti hundaa'e yoo ta'u, aangoo, dhaabbilee fi walitti bu'iinsa "
                 "Itiyoophiyaa fi Gaanfa Afrikaa keessatti xiinxala.\n\n## Ergama keenya\n\nXiinxala siyaasaa cimaa fi ragaadhaan deggeramee "
                 "barattootaaf, hayyootaaf, gaazexeessitootaaf fi ogeeyyiif dhiyeessuu.\n\n## Waan maxxansinu\n\n- Barreeffamoota xiinxalaa "
                 "gabaabaa fi yaadannoo qorannoo\n- Mormii qindaa'e\n- Tarreeffama dubbisaa, daataa fi waraqaa hojii Kuusaa Barreeffamaa keenya keessatti"),
    "about_ar": ("منتدى هورن بوليتي منصة مستقلة قائمة على البحث لتحليل السلطة والمؤسسات والنزاع في إثيوبيا ومنطقة القرن الأفريقي.\n\n"
                 "## مهمتنا\n\nإتاحة تحليل سياسي رصين قائم على الأدلة للطلاب والباحثين والصحفيين والممارسين.\n\n"
                 "## ما ننشره\n\n- مقالات تحليلية قصيرة ومذكرات بحثية\n- نقاشات منظمة\n- قوائم قراءة وبيانات وأوراق عمل في مكتبتنا"),
    "online_requires_approval": "0", "slider_height": "520", "slider_speed": "6",
}


def ensure_columns(conn):
    """Upgrade older databases in place."""
    for table, cols in ADD_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def seed_extras(conn, fresh):
    now = utcnow()
    for k, v in SITE_DEFAULTS.items():
        if get_setting(conn, k) is None:
            set_setting(conn, k, v)
    if conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO plans (key,name,price_etb,price_usd,price_eur,period_days,benefits,custom,active,sort) VALUES (?,?,?,?,?,?,?,?,1,?)",
            [("reader", "Reader", 0, 0, 0, 0, "Public essays, comments, newsletter and member-only documents.", 0, 1),
             ("supporter", "Supporter", 300, 5, 5, 30, "Everything in Reader + exclusive essays and monthly reading notes.", 0, 2),
             ("researcher", "Research Circle", 700, 12, 11, 30, "Draft chapters, datasets, premium library and small-group seminars.", 0, 3),
             ("institutional", "Institutional", 0, 0, 0, 30, "For departments, think-tanks and NGOs. Multi-user access, tailored content.", 1, 4)])
    if conn.execute("SELECT COUNT(*) FROM payment_methods").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO payment_methods (kind,label,account_name,account_number,instructions,enabled,sort) VALUES (?,?,?,?,?,?,?)",
            [("chapa", "Pay online – Telebirr, CBE Birr, bank & cards (via Chapa)", "", "",
              "You will be sent to a secure Chapa page to complete payment.", 1, 1),
             ("telebirr", "Telebirr (send to our number)", "", "",
              "Open Telebirr, choose Send Money, pay the exact amount, then enter the transaction ID from the SMS receipt.", 0, 2),
             ("bank", "Bank transfer (Commercial Bank of Ethiopia)", "", "",
              "Transfer the exact amount and keep your receipt. Enter the transaction reference or upload a screenshot.", 0, 3)])
    # international methods (added for new AND upgraded databases); currencies per method
    conn.execute("UPDATE payment_methods SET currencies='ETB' WHERE kind IN ('chapa','telebirr','bank','cbebirr','mpesa') AND currencies=''")
    for kind, label, cur, ins, en in [
            ("card", "Visa / Mastercard bank card", "USD,EUR", "You will be sent to a secure card page. Visa and Mastercard are accepted.", 1),
            ("stripe", "Card payment – Visa / Mastercard (Stripe)", "USD,EUR", "You will be sent to Stripe's secure page to pay by card.", 0),
            ("paypal", "PayPal", "USD,EUR", "You will be sent to PayPal to approve the payment.", 1),
            ("alipay", "Alipay", "USD,EUR", "You will be sent to Alipay to approve the payment.", 1),
            ("payoneer", "Payoneer", "USD,EUR", "Pay from your Payoneer account to the account below (or use the payment link), then enter the transaction ID or upload a screenshot.", 0),
            ("alipay_qr", "Alipay (scan QR code)", "USD,EUR", "Scan the QR code with Alipay, pay the exact amount, then enter the transaction ID or upload a screenshot.", 0),
            ("wire", "International bank transfer (SWIFT / IBAN)", "USD,EUR", "Send the exact amount by bank transfer and keep the receipt. Enter the reference or upload a screenshot.", 0)]:
        if conn.execute("SELECT 1 FROM payment_methods WHERE kind = ?", (kind,)).fetchone() is None:
            conn.execute("INSERT INTO payment_methods (kind,label,account_name,account_number,instructions,enabled,sort,currencies) VALUES (?,?,?,?,?,?,20,?)",
                         (kind, label, "", "", ins, en, cur))
    if conn.execute("SELECT COUNT(*) FROM slides").fetchone()[0] == 0:
        conn.executemany("INSERT INTO slides (title,subtitle,image_url,link,cta,active,sort) VALUES (?,?,?,?,?,1,?)", [
            ("Critical debate on power, institutions and conflict", "A research-driven space for analysis of Ethiopia and the Horn of Africa.", "/static/img/hero1.svg", "#articles", "Read latest analysis", 1),
            ("A growing library of papers, datasets and guides", "Download working papers and reading lists – free and members-only.", "/static/img/hero2.svg", "#/library", "Open the Library", 2),
            ("Support independent analysis", "Join free, or become a Supporter – pay by Telebirr, bank, card or PayPal.", "/static/img/hero3.svg", "#/membership", "See membership plans", 3)])
    if conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0:
        def d(days, hh):
            return (datetime.now() + timedelta(days=days)).strftime(f"%Y-%m-%dT{hh}")
        conn.executemany(
            "INSERT INTO events (title,starts_at,ends_at,location,online_url,description,published,created_at) VALUES (?,?,?,?,?,?,1,?)",
            [("Online seminar: Reading the Horn as a Regional System", d(12, "15:00"), d(12, "16:30"), "Online", "",
              "A moderated discussion on regional security dynamics. Open to all members.", now),
             ("Research Circle workshop: Using Event Data Responsibly", d(35, "10:00"), d(35, "12:00"), "Addis Ababa (venue TBA)", "",
              "Hands-on methods workshop for researchers and graduate students.", now),
             ("Past event: Launch of Horn Polity Forum", d(-25, "14:00"), "", "Online", "",
              "Opening discussion on the purpose and direction of the forum.", now)])
    if fresh and conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0:
        samples = [("Welcome & Reading Guide", "How to get the most from the forum.", "Guides", "public",
                    "Horn Polity Forum - Reading Guide\n\n1. Start with the featured essays.\n2. Use the Library for documents.\n3. Join the discussion in the comments.\n"),
                   ("Members-only sample: Research Checklist", "Sample members-only document.", "Methods", "members",
                    "Research checklist (members)\n\n- State the question\n- Name the evidence\n- Report uncertainty\n")]
        for title, desc, cat, access, body in samples:
            stored = secrets.token_hex(12) + ".txt"
            (DOC_DIR / stored).write_text(body, encoding="utf-8")
            conn.execute("INSERT INTO documents (title,description,category,access,stored_name,original_name,ext,size,created_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?)",
                         (title, desc, cat, access, stored, title.replace(" ", "_") + ".txt", "txt", len(body), now))


def init_db() -> None:
    """Create tables, upgrade old databases and seed sample content (safe to call repeatedly)."""
    for d in (DOC_DIR, PROOF_DIR, MEDIA_DIR):
        os.makedirs(d, exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA)
        ensure_columns(conn)
        fresh = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0
        if fresh:
            for title, cat, tags, excerpt, body, feat, views, likes, when in SEED:
                conn.execute(
                    "INSERT INTO articles (slug,title,category,tags,excerpt,body,author,featured,"
                    "published,views,likes,published_at,updated_at) VALUES (?,?,?,?,?,?,?,?,1,?,?,?,?)",
                    (unique_slug(conn, title), title, cat, tags, excerpt, body,
                     "Editorial Board", feat, views, likes, when, when))
            conn.execute("UPDATE articles SET access='premium' WHERE title LIKE 'Elite Co-optation%'")
            conn.execute("UPDATE articles SET access='members' WHERE title LIKE 'Methods Note%'")
        seed_extras(conn, fresh)
