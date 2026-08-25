import os
import random
import string
import hashlib
import html
import json
import urllib.request
from functools import wraps
from urllib.parse import urlparse

import psycopg
from dotenv import load_dotenv
from flask import Flask, request, redirect, jsonify, abort, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)

SECRET_KEY = (os.getenv("SECRET_KEY") or "").strip()
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
ADMIN_EMAIL = (os.getenv("ADMIN_EMAIL") or "").strip().lower()

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY not found in environment variables")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not found in environment variables")

IS_PRODUCTION = (
    os.getenv("RENDER", "").lower() == "true"
    or bool(os.getenv("RENDER_EXTERNAL_URL"))
)

app.secret_key = SECRET_KEY
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=__import__("datetime").timedelta(days=7),
)

SUPPORT_NAME = "Shuvo Ahmed"
SUPPORT_HANDLE = "@Ahmed_shuvo_786"
SUPPORT_URL = "https://t.me/Ahmed_shuvo_786"

COUNTRY_NAMES = {
    "BD":"Bangladesh","IN":"India","US":"United States","GB":"United Kingdom",
    "UK":"United Kingdom","AE":"United Arab Emirates","SA":"Saudi Arabia",
    "PK":"Pakistan","CA":"Canada","AU":"Australia","DE":"Germany","FR":"France",
    "SG":"Singapore","MY":"Malaysia","NP":"Nepal","LK":"Sri Lanka","TR":"Turkey",
    "JP":"Japan","KR":"South Korea","CN":"China","BR":"Brazil","NG":"Nigeria",
    "EG":"Egypt",
}

BOT_HINTS = (
    "facebookexternalhit","facebot","meta-externalagent","meta-externalfetcher",
    "twitterbot","linkedinbot","slackbot","whatsapp","telegrambot",
    "googlebot","bingbot","preview",
)

def get_db():
    # Render/Supabase URLs can occasionally contain surrounding whitespace.
    return psycopg.connect(DATABASE_URL, connect_timeout=10)

def setup_database():
    """Create the schema and safely migrate older SmartLink databases."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT,
                    short_code TEXT UNIQUE NOT NULL,
                    original_url TEXT NOT NULL,
                    clicks BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS click_logs (
                    id BIGSERIAL PRIMARY KEY,
                    link_id BIGINT,
                    short_code TEXT NOT NULL,
                    country TEXT DEFAULT 'Unknown',
                    device TEXT DEFAULT 'Others',
                    operating_system TEXT DEFAULT 'Others',
                    browser TEXT DEFAULT 'Others',
                    ip_hash TEXT,
                    clicked_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            # Safe migrations for databases created by older versions.
            cur.execute("ALTER TABLE links ADD COLUMN IF NOT EXISTS user_id BIGINT")
            cur.execute("ALTER TABLE links ADD COLUMN IF NOT EXISTS short_code TEXT")
            cur.execute("ALTER TABLE links ADD COLUMN IF NOT EXISTS original_url TEXT")
            cur.execute("ALTER TABLE links ADD COLUMN IF NOT EXISTS clicks BIGINT DEFAULT 0")
            cur.execute("ALTER TABLE links ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()")

            cur.execute("ALTER TABLE click_logs ADD COLUMN IF NOT EXISTS link_id BIGINT")
            cur.execute("ALTER TABLE click_logs ADD COLUMN IF NOT EXISTS short_code TEXT")
            cur.execute("ALTER TABLE click_logs ADD COLUMN IF NOT EXISTS country TEXT DEFAULT 'Unknown'")
            cur.execute("ALTER TABLE click_logs ADD COLUMN IF NOT EXISTS device TEXT DEFAULT 'Others'")
            cur.execute("ALTER TABLE click_logs ADD COLUMN IF NOT EXISTS operating_system TEXT DEFAULT 'Others'")
            cur.execute("ALTER TABLE click_logs ADD COLUMN IF NOT EXISTS browser TEXT DEFAULT 'Others'")
            cur.execute("ALTER TABLE click_logs ADD COLUMN IF NOT EXISTS ip_hash TEXT")
            cur.execute("ALTER TABLE click_logs ADD COLUMN IF NOT EXISTS clicked_at TIMESTAMPTZ DEFAULT NOW()")

            # Backfill null defaults where possible.
            cur.execute("UPDATE links SET clicks=0 WHERE clicks IS NULL")
            cur.execute("UPDATE links SET created_at=NOW() WHERE created_at IS NULL")
            cur.execute("UPDATE click_logs SET country='Unknown' WHERE country IS NULL")
            cur.execute("UPDATE click_logs SET device='Others' WHERE device IS NULL")
            cur.execute("UPDATE click_logs SET operating_system='Others' WHERE operating_system IS NULL")
            cur.execute("UPDATE click_logs SET browser='Others' WHERE browser IS NULL")
            cur.execute("UPDATE click_logs SET clicked_at=NOW() WHERE clicked_at IS NULL")

            # Foreign keys are added only if they do not already exist.
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'links_user_id_fkey'
                    ) THEN
                        ALTER TABLE links
                        ADD CONSTRAINT links_user_id_fkey
                        FOREIGN KEY (user_id) REFERENCES users(id)
                        ON DELETE CASCADE;
                    END IF;
                END $$;
            """)
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'click_logs_link_id_fkey'
                    ) THEN
                        ALTER TABLE click_logs
                        ADD CONSTRAINT click_logs_link_id_fkey
                        FOREIGN KEY (link_id) REFERENCES links(id)
                        ON DELETE CASCADE;
                    END IF;
                END $$;
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_links_user_id ON links(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_links_short_code ON links(short_code)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_click_logs_link_id ON click_logs(link_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_click_logs_clicked_at ON click_logs(clicked_at)")
        conn.commit()

def db_error_text(exc):
    return f"{type(exc).__name__}: {exc}"

def generate_short_code(length=7):
    chars = string.ascii_letters + string.digits
    with get_db() as conn:
        with conn.cursor() as cur:
            for _ in range(100):
                code = "".join(random.choice(chars) for _ in range(length))
                cur.execute("SELECT 1 FROM links WHERE short_code=%s", (code,))
                if cur.fetchone() is None:
                    return code
    raise RuntimeError("Unable to generate unique short code")

def get_client_ip():
    for header in ("CF-Connecting-IP","True-Client-IP","X-Real-IP","X-Forwarded-For","X-Client-IP"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()
    return request.remote_addr or ""

def is_bot(user_agent):
    ua = (user_agent or "").lower()
    return any(hint in ua for hint in BOT_HINTS)

def _fetch_json(url, timeout=1.5):
    req = urllib.request.Request(url, headers={"User-Agent":"SmartLink/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def get_country(ip, user_agent=""):
    try:
        header_code = (
            request.headers.get("CF-IPCountry")
            or request.headers.get("CloudFront-Viewer-Country")
            or request.headers.get("X-AppEngine-Country")
        )
        if header_code:
            code = header_code.strip().upper()
            if code not in ("XX","T1","ZZ",""):
                return COUNTRY_NAMES.get(code, code)

        if not ip or ip in ("127.0.0.1","::1"):
            return "Local"
        if is_bot(user_agent):
            return "Bot / Preview"

        lookups = [
            ("https://ipwho.is/" + ip,
             lambda d: d.get("country") if d.get("success") else None),
            ("https://ipapi.co/" + ip + "/json/",
             lambda d: None if d.get("error") else d.get("country_name")),
            ("http://ip-api.com/json/" + ip + "?fields=status,country",
             lambda d: d.get("country") if d.get("status") == "success" else None),
        ]
        for lookup_url, picker in lookups:
            try:
                country = picker(_fetch_json(lookup_url))
                if country:
                    return str(country)
            except Exception:
                continue
    except Exception:
        pass
    return "Unknown"

def get_device(user_agent):
    ua = (user_agent or "").lower()
    if is_bot(user_agent): return "Bot / Preview"
    if "ipad" in ua: return "iPad"
    if "iphone" in ua: return "iPhone"
    if "android" in ua and "mobile" in ua: return "Android"
    if "android" in ua: return "Android Tablet"
    if "windows" in ua: return "Windows PC"
    if "macintosh" in ua or "mac os" in ua: return "Mac"
    if "linux" in ua: return "Linux"
    return "Others"

def get_operating_system(user_agent):
    ua = (user_agent or "").lower()
    if is_bot(user_agent): return "Bot"
    if "iphone" in ua or "ipad" in ua: return "iOS"
    if "android" in ua: return "Android"
    if "windows" in ua: return "Windows"
    if "mac os" in ua or "macintosh" in ua: return "macOS"
    if "linux" in ua: return "Linux"
    return "Others"

def get_browser(user_agent):
    ua = (user_agent or "").lower()
    if is_bot(user_agent): return "Bot / Crawler"
    if "edg/" in ua: return "Microsoft Edge"
    if "opr/" in ua or "opera" in ua: return "Opera"
    if "firefox/" in ua or "fxios" in ua: return "Mozilla Firefox"
    if "chrome/" in ua or "crios" in ua: return "Google Chrome"
    if "safari/" in ua and "chrome" not in ua: return "Safari"
    return "Others"

def hash_ip(ip):
    return hashlib.sha256((ip or "").encode("utf-8")).hexdigest()

def format_dt(dt):
    if not dt: return "—"
    try: return dt.strftime("%d %b %Y  ·  %I:%M %p")
    except Exception: return str(dt)

def is_safe_next_url(value):
    if not value: return False
    value = value.strip()
    if not value.startswith("/") or value.startswith("//"): return False
    parsed = urlparse(value)
    return not parsed.scheme and not parsed.netloc

def current_user():
    uid = session.get("user_id")
    if not uid: return None
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id,name,email,is_admin FROM users WHERE id=%s",
                    (uid,)
                )
                row = cur.fetchone()
        if not row:
            session.clear()
            return None
        user_id, name, email, database_admin = row
        env_admin = bool(ADMIN_EMAIL and email.strip().lower() == ADMIN_EMAIL)
        return {
            "id": user_id,
            "name": name,
            "email": email,
            "is_admin": bool(database_admin or env_admin),
        }
    except Exception as exc:
        print("CURRENT USER ERROR:", db_error_text(exc), flush=True)
        return None

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            next_path = request.path
            if request.query_string:
                next_path += "?" + request.query_string.decode("utf-8", errors="ignore")
            return redirect(url_for("signin", next=next_path))
        return view(*args, **kwargs)
    return wrapped

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for("signin", next=request.path))
        if not user["is_admin"]:
            abort(403)
        return view(*args, **kwargs)
    return wrapped

CSS = """
:root{--ink:#08090c;--panel:#12141a;--raised:#1b1f28;--line:#2c313c;--gold:#d4af37;--ivory:#f4efe4;--muted:#9a9386;--danger:#f87171}
*{box-sizing:border-box;margin:0;padding:0}html,body{min-height:100%}
body{font-family:Outfit,system-ui,sans-serif;background:radial-gradient(ellipse at top,rgba(212,175,55,.08),transparent 55%),var(--ink);color:var(--ivory)}
a{color:inherit}.wrap{max-width:1100px;margin:0 auto;padding:0 20px}
header{border-bottom:1px solid var(--line);position:sticky;top:0;z-index:20;background:rgba(8,9,12,.88);backdrop-filter:blur(12px)}
.nav{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px 0;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:12px;text-decoration:none}.mark{width:36px;height:36px;border:1px solid rgba(212,175,55,.4);border-radius:8px;display:grid;place-items:center;color:var(--gold)}
.brand b{display:block;font-family:"Cormorant Garamond",serif;font-size:20px}.brand small{display:block;letter-spacing:.22em;text-transform:uppercase;font-size:10px;color:var(--muted)}
.menu{display:flex;flex-wrap:wrap;gap:4px;align-items:center}.menu a,.menu button{background:none;border:0;color:var(--muted);padding:10px 12px;border-radius:8px;text-decoration:none;font-size:14px;cursor:pointer}.menu a.active,.menu a:hover,.menu button:hover{color:var(--ivory);background:var(--raised)}
.menu .gold,.gold{color:var(--gold)}main{padding:40px 0 72px}h1,h2,h3{font-family:"Cormorant Garamond",serif;font-weight:600}
.hero h1{font-size:clamp(36px,6vw,58px);line-height:.95;margin:12px 0 16px}.hero p{color:var(--muted);max-width:520px;line-height:1.6}
.kicker{color:var(--gold);letter-spacing:.28em;text-transform:uppercase;font-size:11px}
form.row{display:flex;gap:12px;margin-top:32px}form.stack{display:flex;flex-direction:column;gap:14px;margin-top:24px;max-width:420px}form.stack label{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
input{width:100%;min-height:52px;border:1px solid var(--line);background:var(--panel);color:var(--ivory);border-radius:10px;padding:0 16px;font:inherit;outline:none}input:focus{border-color:var(--gold)}
.btn{min-height:52px;border:0;border-radius:10px;background:var(--gold);color:var(--ink);font-weight:700;padding:0 22px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;white-space:nowrap}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:28px 0}.stat,.card,.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px}.stat{padding:22px}.stat b{display:block;font-family:"Cormorant Garamond",serif;font-size:36px;color:var(--gold)}.stat span{color:var(--muted);font-size:12px;letter-spacing:.16em;text-transform:uppercase}
.card{overflow:hidden}.card-h{padding:20px 22px;border-bottom:1px solid var(--line)}.card-h p{color:var(--muted);font-size:14px;margin-top:4px}.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:720px}th{text-align:left;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:500;background:var(--raised);padding:12px 18px}td{padding:14px 18px;border-top:1px solid var(--line);font-size:14px;vertical-align:middle}
.muted{color:var(--muted)}.err{color:var(--danger);font-size:14px;margin-top:10px}.tag{display:inline-block;background:var(--raised);color:var(--gold);padding:4px 10px;border-radius:6px;font-size:13px;font-weight:600}
.grid3{display:grid;gap:12px;grid-template-columns:1fr;margin:22px 0}.panel{padding:20px}.chip{display:flex;justify-content:space-between;gap:12px;padding:8px 0;font-size:14px;border-bottom:1px solid var(--line)}.chip:last-child{border:0}
footer{border-top:1px solid var(--line);padding:22px 0;color:var(--muted);font-size:14px}.foot{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.modal-bg{position:fixed;inset:0;background:rgba(8,9,12,.82);display:none;place-items:center;padding:16px;z-index:50}.modal-bg.open{display:grid}.modal{width:min(440px,100%);background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:24px}.tg{display:block;margin-top:18px;padding:18px;border:1px solid rgba(212,175,55,.4);border-radius:12px;text-decoration:none;background:var(--raised)}.tg b{display:block;font-family:"Cormorant Garamond",serif;font-size:28px}.tg span{color:var(--gold)}.auth-box{max-width:460px;margin:0 auto}
@media(min-width:800px){.grid3{grid-template-columns:1fr 1fr 1fr}}@media(max-width:700px){form.row{flex-direction:column}.btn{width:100%}}
"""

def layout(title, body, active=""):
    user = current_user()
    def nav(href,key,label):
        cls = "active" if active == key else ""
        return f'<a class="{cls}" href="{href}">{label}</a>'
    if user:
        admin_link = nav("/admin","admin","Admin") if user["is_admin"] else ""
        auth_links = (
            nav("/","home","Create") + nav("/dashboard","dashboard","Dashboard") +
            nav("/live-console","live","Live") + admin_link +
            f'<span class="muted" style="padding:0 8px;font-size:13px">{html.escape(user["name"])}</span>' +
            '<a href="/signout">Sign out</a>'
        )
    else:
        auth_links = nav("/signin","signin","Sign in") + nav("/signup","signup","Sign up")
    return f"""<!doctype html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><header><div class="wrap nav">
<a class="brand" href="/"><span class="mark">◆</span><span><b>SmartLink</b><small>Private workspace</small></span></a>
<nav class="menu">{auth_links}<button type="button" class="gold" onclick="openSupport()">Support</button></nav>
</div></header><main><div class="wrap">{body}</div></main><footer><div class="wrap foot"><span>SmartLink</span>
<button type="button" class="gold" style="background:none;border:0;cursor:pointer;font:inherit" onclick="openSupport()">Support · Telegram</button>
</div></footer>
<div class="modal-bg" id="supportModal" onclick="if(event.target===this)closeSupport()"><div class="modal">
<p class="kicker">Support</p><h2 style="font-size:32px;margin:8px 0 10px">Direct line</h2><p class="muted">Tap the name to open Telegram.</p>
<a class="tg" href="{SUPPORT_URL}" target="_blank" rel="noopener noreferrer"><b>{SUPPORT_NAME}</b><span>{SUPPORT_HANDLE}</span><p class="muted" style="margin-top:10px;letter-spacing:.16em;text-transform:uppercase;font-size:11px">Open Telegram →</p></a>
<p style="margin-top:14px"><button type="button" onclick="closeSupport()" style="background:none;border:0;color:var(--muted);cursor:pointer">Close</button></p>
</div></div>
<script>
function openSupport(){{document.getElementById("supportModal").classList.add("open")}}
function closeSupport(){{document.getElementById("supportModal").classList.remove("open")}}
</script></body></html>"""

@app.route("/signup", methods=["GET","POST"])
def signup():
    if current_user(): return redirect("/")
    error = ""
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if len(name) < 2: error = "Name is too short."
        elif "@" not in email or "." not in email: error = "Enter a valid email."
        elif len(password) < 6: error = "Password must be at least 6 characters."
        else:
            try:
                with get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT id FROM users WHERE email=%s",(email,))
                        if cur.fetchone():
                            error = "Email already registered. Please sign in."
                        else:
                            is_admin = bool(ADMIN_EMAIL and email == ADMIN_EMAIL)
                            cur.execute("""INSERT INTO users(name,email,password_hash,is_admin)
                                           VALUES(%s,%s,%s,%s) RETURNING id""",
                                        (name,email,generate_password_hash(password),is_admin))
                            uid = cur.fetchone()[0]
                            conn.commit()
                if not error:
                    session.clear()
                    session["user_id"] = uid
                    session.permanent = True
                    return redirect("/")
            except Exception as exc:
                print("SIGNUP ERROR:",db_error_text(exc),flush=True)
                error = "Signup failed. Please try again."
    err = f"<p class='err'>{html.escape(error)}</p>" if error else ""
    body = f"""<div class="auth-box"><p class="kicker">Account</p><h1>Create your workspace</h1>
<p class="muted" style="margin-top:8px">Your links stay private — only you can see them.</p>
<form class="stack" method="POST" action="/signup">
<div><label>Name</label><input type="text" name="name" required minlength="2" placeholder="Your name"></div>
<div><label>Email</label><input type="email" name="email" required placeholder="you@email.com"></div>
<div><label>Password</label><input type="password" name="password" required minlength="6" placeholder="Min 6 characters"></div>
<button class="btn" type="submit">Sign up</button></form>{err}
<p class="muted" style="margin-top:18px">Already have an account? <a class="gold" href="/signin">Sign in</a></p></div>"""
    return layout("Sign up · SmartLink",body,"signup")

@app.route("/signin", methods=["GET","POST"])
def signin():
    if current_user(): return redirect("/")
    error = ""
    next_url = request.args.get("next") or request.form.get("next") or "/"
    if not is_safe_next_url(next_url): next_url = "/"
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id,password_hash FROM users WHERE email=%s",(email,))
                    row = cur.fetchone()
            if not row or not check_password_hash(row[1],password):
                error = "Invalid email or password."
            else:
                session.clear()
                session["user_id"] = row[0]
                session.permanent = True
                return redirect(next_url if is_safe_next_url(next_url) else "/")
        except Exception as exc:
            print("SIGNIN ERROR:",db_error_text(exc),flush=True)
            error = "Sign in failed. Please try again."
    err = f"<p class='err'>{html.escape(error)}</p>" if error else ""
    body = f"""<div class="auth-box"><p class="kicker">Welcome back</p><h1>Sign in</h1>
<form class="stack" method="POST" action="/signin"><input type="hidden" name="next" value="{html.escape(next_url,quote=True)}">
<div><label>Email</label><input type="email" name="email" required placeholder="you@email.com"></div>
<div><label>Password</label><input type="password" name="password" required placeholder="Your password"></div>
<button class="btn" type="submit">Sign in</button></form>{err}
<p class="muted" style="margin-top:18px">New here? <a class="gold" href="/signup">Create account</a></p></div>"""
    return layout("Sign in · SmartLink",body,"signin")

@app.route("/signout")
def signout():
    session.clear()
    return redirect("/signin")

@app.route("/")
@login_required
def home():
    body = """<section class="hero"><p class="kicker">Your private links</p><h1>Create a short link.</h1>
<p>Only you can see the links you create. Clicks record country, device, OS, browser, date and time.</p>
<form class="row" method="POST" action="/create"><input type="url" name="url" placeholder="https://example.com/your-page" required>
<button class="btn" type="submit">Create link</button></form></section>"""
    return layout("SmartLink",body,"home")

@app.route("/create", methods=["POST"])
@login_required
def create_link():
    user = current_user()
    if not user:
        return redirect(url_for("signin",next="/"))
    try:
        original_url = (request.form.get("url") or "").strip()
        parsed = urlparse(original_url)
        if parsed.scheme.lower() not in ("http","https") or not parsed.netloc:
            return "Invalid URL",400

        # Insert with retry so a rare short-code collision cannot break creation.
        inserted = False
        short_code = None
        for _ in range(10):
            candidate = generate_short_code()
            try:
                with get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""INSERT INTO links(user_id,short_code,original_url,clicks)
                                       VALUES(%s,%s,%s,0) RETURNING short_code""",
                                    (user["id"],candidate,original_url))
                        short_code = cur.fetchone()[0]
                    conn.commit()
                inserted = True
                break
            except psycopg.errors.UniqueViolation:
                continue

        if not inserted:
            raise RuntimeError("Could not reserve a unique short code")

        short_url = request.host_url.rstrip("/") + "/" + short_code
        safe = html.escape(short_url)
        body = f"""<p class="kicker">Ready</p><h1>Link created</h1>
<div class="card" style="margin-top:24px;padding:24px"><p class="muted">Your private SmartLink</p>
<p style="margin:10px 0 18px;word-break:break-all"><a class="gold" href="{safe}">{safe}</a></p>
<a class="btn" href="/dashboard">Open dashboard</a></div>"""
        return layout("Link created · SmartLink",body,"home")
    except Exception as exc:
        print("========== CREATE LINK ERROR ==========",flush=True)
        print(db_error_text(exc),flush=True)
        import traceback
        traceback.print_exc()
        print("=======================================",flush=True)
        return "Unable to create link. Please try again.",500

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT short_code,original_url,clicks,created_at
                               FROM links WHERE user_id=%s ORDER BY id DESC""",(user["id"],))
                links = cur.fetchall()
                cur.execute("SELECT COUNT(*) FROM links WHERE user_id=%s",(user["id"],))
                total_links = cur.fetchone()[0]
                cur.execute("SELECT COALESCE(SUM(clicks),0) FROM links WHERE user_id=%s",(user["id"],))
                total_clicks = cur.fetchone()[0]
    except Exception as exc:
        print("DASHBOARD ERROR:",db_error_text(exc),flush=True)
        return "Dashboard error. Please try again.",500

    rows=""
    for short,original_url,clicks,created in links:
        safe_url=html.escape(original_url)
        display=safe_url if len(original_url)<58 else html.escape(original_url[:55]+"...")
        rows += f"""<tr><td><a class="gold" href="/{html.escape(short)}">/{html.escape(short)}</a></td>
<td class="muted" title="{safe_url}">{display}</td><td>{int(clicks)}</td><td class="muted">{format_dt(created)}</td>
<td><a class="gold" href="/analytics/{html.escape(short)}">View A–Z</a></td></tr>"""
    if not rows:
        rows='<tr><td colspan="5" class="muted" style="text-align:center;padding:48px">No links yet.</td></tr>'
    body=f"""<p class="kicker">Only your data</p><h1>Dashboard</h1>
<div class="stats"><div class="stat"><b>{total_links}</b><span>Your links</span></div>
<div class="stat"><b>{total_clicks}</b><span>Your clicks</span></div></div>
<div class="card"><div class="card-h"><h2>Your SmartLinks</h2><p>Other users cannot see these links.</p></div>
<div class="table-wrap"><table><thead><tr><th>Short link</th><th>Destination</th><th>Clicks</th><th>Created</th><th>Details</th></tr></thead>
<tbody>{rows}</tbody></table></div></div>"""
    return layout("Dashboard · SmartLink",body,"dashboard")

@app.route("/analytics/<short_code>")
@login_required
def analytics(short_code):
    user=current_user()
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT id,short_code,original_url,clicks,created_at,user_id
                               FROM links WHERE short_code=%s""",(short_code,))
                link=cur.fetchone()
                if not link: abort(404)
                link_id,sc,original_url,clicks,created_at,owner_id=link
                if owner_id != user["id"] and not user["is_admin"]: abort(403)
                cur.execute("""SELECT country,device,operating_system,browser,clicked_at
                               FROM click_logs WHERE link_id=%s ORDER BY id DESC LIMIT 200""",(link_id,))
                click_rows=cur.fetchall()
                cur.execute("""SELECT country,COUNT(*) FROM click_logs WHERE link_id=%s
                               GROUP BY country ORDER BY COUNT(*) DESC LIMIT 8""",(link_id,))
                top_countries=cur.fetchall()
                cur.execute("""SELECT device,COUNT(*) FROM click_logs WHERE link_id=%s
                               GROUP BY device ORDER BY COUNT(*) DESC LIMIT 8""",(link_id,))
                top_devices=cur.fetchall()
                cur.execute("""SELECT browser,COUNT(*) FROM click_logs WHERE link_id=%s
                               GROUP BY browser ORDER BY COUNT(*) DESC LIMIT 8""",(link_id,))
                top_browsers=cur.fetchall()
    except Exception as exc:
        if getattr(exc,"code",None) in (403,404): raise
        print("ANALYTICS ERROR:",db_error_text(exc),flush=True)
        return "Analytics error. Please try again.",500

    def chips(items):
        if not items: return '<p class="muted">No data yet</p>'
        return "".join(f'<div class="chip"><span>{html.escape(str(n or "Unknown"))}</span><b class="gold">{int(c)}</b></div>' for n,c in items)

    rows=""
    for country,device,os_name,browser,clicked_at in click_rows:
        rows += f"""<tr><td><span class="tag">{html.escape(country or "Unknown")}</span></td>
<td>{html.escape(device or "Others")}</td><td>{html.escape(os_name or "Others")}</td>
<td>{html.escape(browser or "Others")}</td><td class="muted">{format_dt(clicked_at)}</td></tr>"""
    if not rows:
        rows='<tr><td colspan="5" class="muted" style="text-align:center;padding:48px">No clicks yet.</td></tr>'
    body=f"""<p><a class="gold" href="/dashboard">← Dashboard</a></p><h1 style="margin-top:12px">/{html.escape(sc)}</h1>
<p class="muted" style="margin:8px 0 16px;word-break:break-all">{html.escape(original_url)}</p>
<p style="font-family:'Cormorant Garamond',serif;font-size:48px;color:var(--gold)">{int(clicks)}
<span class="muted" style="font-size:22px">clicks</span></p><p class="muted">Created {format_dt(created_at)}</p>
<div class="grid3"><div class="panel"><p class="kicker">Countries</p>{chips(top_countries)}</div>
<div class="panel"><p class="kicker">Devices</p>{chips(top_devices)}</div><div class="panel"><p class="kicker">Browsers</p>{chips(top_browsers)}</div></div>
<div class="card"><div class="card-h"><h2>Click log</h2><p>Country · device · OS · browser · date · time</p></div>
<div class="table-wrap"><table><thead><tr><th>Country</th><th>Device</th><th>OS</th><th>Browser</th><th>Date & time</th></tr></thead>
<tbody>{rows}</tbody></table></div></div>"""
    return layout(f"Analytics · /{sc}",body,"dashboard")

@app.route("/api/live-clicks")
@login_required
def live_clicks():
    user=current_user()
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                if user["is_admin"]:
                    cur.execute("""SELECT id,short_code,country,device,operating_system,browser,clicked_at
                                   FROM click_logs ORDER BY id DESC LIMIT 120""")
                else:
                    cur.execute("""SELECT cl.id,cl.short_code,cl.country,cl.device,cl.operating_system,cl.browser,cl.clicked_at
                                   FROM click_logs cl JOIN links l ON l.id=cl.link_id
                                   WHERE l.user_id=%s ORDER BY cl.id DESC LIMIT 120""",(user["id"],))
                rows=cur.fetchall()
        return jsonify([{"id":r[0],"short_code":r[1],"country":r[2] or "Unknown",
                         "device":r[3] or "Others","os":r[4] or "Others",
                         "browser":r[5] or "Others","clicked_at":r[6].isoformat() if r[6] else None} for r in rows])
    except Exception as exc:
        print("LIVE API ERROR:",db_error_text(exc),flush=True)
        return jsonify({"error":"Unable to load live clicks"}),500

@app.route("/live-console")
@login_required
def live_console():
    body="""<p class="kicker">Live</p><h1>Click console</h1><p class="muted" style="margin:8px 0 22px">Only your links (admin sees all).</p>
<div class="card"><input id="search" placeholder="Search…"><div class="table-wrap"><table><thead><tr>
<th>Date & time</th><th>Link</th><th>Country</th><th>Device</th><th>OS</th><th>Browser</th></tr></thead>
<tbody id="events"><tr><td colspan="6" class="muted" style="text-align:center;padding:48px">Waiting…</td></tr></tbody></table></div></div>
<script>
let events=[];
function esc(v){{return String(v??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;")}}
function render(){{let q=document.getElementById("search").value.toLowerCase(),b=document.getElementById("events");
let f=events.filter(e=>(e.short_code+" "+e.country+" "+e.device+" "+e.os+" "+e.browser).toLowerCase().includes(q));
if(!f.length){{b.innerHTML="<tr><td colspan='6' class='muted' style='text-align:center;padding:48px'>No matching events</td></tr>";return}}
b.innerHTML=f.map(e=>`<tr><td class="muted">${esc(e.clicked_at?new Date(e.clicked_at).toLocaleString():"—")}</td>
<td><a class="gold" href="/analytics/${esc(e.short_code)}">/${esc(e.short_code)}</a></td><td><span class="tag">${esc(e.country)}</span></td>
<td>${esc(e.device)}</td><td>${esc(e.os)}</td><td>${esc(e.browser)}</td></tr>`).join("")}}
async function load(){{try{{let r=await fetch("/api/live-clicks",{{cache:"no-store"}});if(!r.ok)return;let d=await r.json();if(Array.isArray(d)){{events=d;render()}}}}catch(e){{}}}}
document.getElementById("search").addEventListener("input",render);load();setInterval(load,2000);
</script>"""
    return layout("Live Console · SmartLink",body,"live")

@app.route("/admin")
@admin_required
def admin_panel():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users"); total_users=cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM links"); total_links=cur.fetchone()[0]
                cur.execute("SELECT COALESCE(SUM(clicks),0) FROM links"); total_clicks=cur.fetchone()[0]
                cur.execute("""SELECT u.id,u.name,u.email,u.is_admin,u.created_at,COUNT(l.id),COALESCE(SUM(l.clicks),0)
                               FROM users u LEFT JOIN links l ON l.user_id=u.id GROUP BY u.id ORDER BY u.id DESC""")
                users=cur.fetchall()
                cur.execute("""SELECT l.short_code,l.original_url,l.clicks,l.created_at,u.email
                               FROM links l LEFT JOIN users u ON u.id=l.user_id ORDER BY l.id DESC LIMIT 100""")
                links=cur.fetchall()
    except Exception as exc:
        print("ADMIN ERROR:",db_error_text(exc),flush=True)
        return "Admin error. Please try again.",500

    user_rows="".join(f"""<tr><td>{int(uid)}</td><td>{html.escape(name)}</td><td>{html.escape(email)}</td>
<td><span class="tag">{"Admin" if is_admin else "User"}</span></td><td>{int(lc)}</td><td>{int(cc)}</td><td class="muted">{format_dt(created)}</td></tr>"""
                      for uid,name,email,is_admin,created,lc,cc in users)
    link_rows="".join(f"""<tr><td><a class="gold" href="/analytics/{html.escape(short)}">/{html.escape(short)}</a></td>
<td class="muted">{html.escape(original_url if len(original_url)<40 else original_url[:37]+"...")}</td><td>{int(clicks)}</td>
<td>{html.escape(email or "—")}</td><td class="muted">{format_dt(created)}</td></tr>"""
                      for short,original_url,clicks,created,email in links)
    if not user_rows: user_rows='<tr><td colspan="7" class="muted" style="text-align:center;padding:32px">No users</td></tr>'
    if not link_rows: link_rows='<tr><td colspan="5" class="muted" style="text-align:center;padding:32px">No links</td></tr>'
    body=f"""<p class="kicker">Admin</p><h1>Control panel</h1><div class="stats">
<div class="stat"><b>{total_users}</b><span>Signups</span></div><div class="stat"><b>{total_links}</b><span>All links</span></div>
<div class="stat"><b>{total_clicks}</b><span>All clicks</span></div></div>
<div class="card" style="margin-bottom:24px"><div class="card-h"><h2>Users</h2><p>Who signed up, when, and their totals</p></div>
<div class="table-wrap"><table><thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Role</th><th>Links</th><th>Clicks</th><th>Joined</th></tr></thead><tbody>{user_rows}</tbody></table></div></div>
<div class="card"><div class="card-h"><h2>Recent links (all users)</h2><p>Latest 100 across the platform</p></div>
<div class="table-wrap"><table><thead><tr><th>Short</th><th>Destination</th><th>Clicks</th><th>Owner</th><th>Created</th></tr></thead><tbody>{link_rows}</tbody></table></div></div>"""
    return layout("Admin · SmartLink",body,"admin")

@app.route("/support")
def support():
    return redirect(SUPPORT_URL)

@app.route("/<short_code>")
@login_required
def redirect_short_link(short_code):
    reserved={"create","dashboard","analytics","live-console","health","api","support","signup","signin","signout","admin"}
    if short_code in reserved: abort(404)
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id,original_url FROM links WHERE short_code=%s",(short_code,))
                link=cur.fetchone()
    except Exception as exc:
        print("REDIRECT LOOKUP ERROR:",db_error_text(exc),flush=True)
        return "Service temporarily unavailable",503
    if not link: abort(404)
    link_id,original_url=link
    try:
        ua=request.headers.get("User-Agent","")
        ip=get_client_ip()
        country=get_country(ip,ua)
        device=get_device(ua)
        os_name=get_operating_system(ua)
        browser=get_browser(ua)
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE links SET clicks=clicks+1 WHERE id=%s",(link_id,))
                cur.execute("""INSERT INTO click_logs(link_id,short_code,country,device,operating_system,browser,ip_hash)
                               VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                            (link_id,short_code,country,device,os_name,browser,hash_ip(ip)))
            conn.commit()
    except Exception as exc:
        print("CLICK LOG ERROR:",db_error_text(exc),flush=True)
    return redirect(original_url,code=302)

@app.route("/health")
def health():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                ok=cur.fetchone()[0]==1
        return jsonify({"status":"ok","database":ok})
    except Exception as exc:
        print("HEALTH ERROR:",db_error_text(exc),flush=True)
        return jsonify({"status":"error","database":False}),500

@app.errorhandler(403)
def forbidden(_):
    return layout("Access denied · SmartLink",
                  "<p class='kicker'>403</p><h1>Access denied</h1><p class='muted'>You do not have permission to view this page.</p>",
                  ""),403

@app.errorhandler(404)
def not_found(_):
    return layout("Not found · SmartLink",
                  "<p class='kicker'>404</p><h1>Page not found</h1><p class='muted'>The requested page or short link does not exist.</p>",
                  ""),404

# Initialize on startup. A deployment must not become unusable because of a
# transient DB connection during import; health logs the actual DB state.
try:
    setup_database()
    print("DATABASE SETUP: OK", flush=True)
except Exception as exc:
    print("DATABASE SETUP FAILED:", db_error_text(exc), flush=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","8080")), debug=False)