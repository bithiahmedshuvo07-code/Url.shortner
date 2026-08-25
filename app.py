import os
import random
import string
import hashlib
import html
import json
import urllib.request
import uuid
from functools import wraps
from urllib.parse import urlparse

import psycopg
from dotenv import load_dotenv
from flask import Flask, request, redirect, jsonify, abort, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)

# =========================================================
# ENVIRONMENT
# =========================================================

SECRET_KEY = os.getenv("SECRET_KEY")

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY not found in environment variables")

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not found in environment variables")

ADMIN_EMAIL = (os.getenv("ADMIN_EMAIL") or "").strip().lower()

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

# =========================================================
# SUPPORT
# =========================================================

SUPPORT_NAME = "Shuvo Ahmed"
SUPPORT_HANDLE = "@Ahmed_shuvo_786"
SUPPORT_URL = "https://t.me/Ahmed_shuvo_786"

# =========================================================
# COUNTRY NAMES
# =========================================================

COUNTRY_NAMES = {
    "BD": "Bangladesh",
    "IN": "India",
    "US": "United States",
    "GB": "United Kingdom",
    "UK": "United Kingdom",
    "AE": "United Arab Emirates",
    "SA": "Saudi Arabia",
    "PK": "Pakistan",
    "CA": "Canada",
    "AU": "Australia",
    "DE": "Germany",
    "FR": "France",
    "SG": "Singapore",
    "MY": "Malaysia",
    "NP": "Nepal",
    "LK": "Sri Lanka",
    "TR": "Turkey",
    "JP": "Japan",
    "KR": "South Korea",
    "CN": "China",
    "BR": "Brazil",
    "NG": "Nigeria",
    "EG": "Egypt",
}

# =========================================================
# BOT / PREVIEW DETECTION
# =========================================================

BOT_HINTS = (
    "facebookexternalhit",
    "facebot",
    "meta-externalagent",
    "meta-externalfetcher",
    "twitterbot",
    "linkedinbot",
    "slackbot",
    "whatsapp",
    "telegrambot",
    "googlebot",
    "bingbot",
    "preview",
)

# =========================================================
# DATABASE
# =========================================================

def get_db():
    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def setup_database():
    """
    UUID-compatible database setup.

    IMPORTANT:
    Existing Supabase/PostgreSQL tables are NOT destroyed.
    Existing UUID users.id / links.user_id remain untouched.
    """

    with get_db() as conn:
        with conn.cursor() as cur:

            # -------------------------------------------------
            # USERS
            # -------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            # -------------------------------------------------
            # LINKS
            # -------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    id BIGSERIAL PRIMARY KEY,
                    user_id UUID
                        REFERENCES users(id)
                        ON DELETE CASCADE,
                    short_code TEXT UNIQUE NOT NULL,
                    original_url TEXT NOT NULL,
                    clicks BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            # -------------------------------------------------
            # CLICK LOGS
            # -------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS click_logs (
                    id BIGSERIAL PRIMARY KEY,
                    link_id BIGINT
                        REFERENCES links(id)
                        ON DELETE CASCADE,
                    short_code TEXT NOT NULL,
                    country TEXT DEFAULT 'Unknown',
                    device TEXT DEFAULT 'Others',
                    operating_system TEXT DEFAULT 'Others',
                    browser TEXT DEFAULT 'Others',
                    ip_hash TEXT,
                    clicked_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            # -------------------------------------------------
            # SAFE MIGRATION FOR OLDER DATABASES
            # -------------------------------------------------

            # Add missing columns if they do not exist.
            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS name TEXT
            """)

            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS email TEXT
            """)

            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS password_hash TEXT
            """)

            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS is_admin BOOLEAN
                DEFAULT FALSE
            """)

            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ
                DEFAULT NOW()
            """)

            cur.execute("""
                ALTER TABLE links
                ADD COLUMN IF NOT EXISTS user_id UUID
            """)

            cur.execute("""
                ALTER TABLE links
                ADD COLUMN IF NOT EXISTS short_code TEXT
            """)

            cur.execute("""
                ALTER TABLE links
                ADD COLUMN IF NOT EXISTS original_url TEXT
            """)

            cur.execute("""
                ALTER TABLE links
                ADD COLUMN IF NOT EXISTS clicks BIGINT
                DEFAULT 0
            """)

            cur.execute("""
                ALTER TABLE links
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ
                DEFAULT NOW()
            """)

            # Make sure admin flag isn't NULL.
            cur.execute("""
                UPDATE users
                SET is_admin = FALSE
                WHERE is_admin IS NULL
            """)

            # Automatically grant admin role to ADMIN_EMAIL.
            if ADMIN_EMAIL:
                cur.execute(
                    """
                    UPDATE users
                    SET is_admin = TRUE
                    WHERE LOWER(TRIM(email)) = %s
                    """,
                    (ADMIN_EMAIL,)
                )

        conn.commit()


# =========================================================
# SHORT CODE
# =========================================================

def generate_short_code(length=7):

    chars = string.ascii_letters + string.digits

    for _ in range(100):

        code = "".join(
            random.choice(chars)
            for _ in range(length)
        )

        with get_db() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT id
                    FROM links
                    WHERE short_code = %s
                    """,
                    (code,)
                )

                if not cur.fetchone():
                    return code

    raise RuntimeError("Unable to generate unique short code")


# =========================================================
# REQUEST / IP
# =========================================================

def get_client_ip():

    for header in (
        "CF-Connecting-IP",
        "True-Client-IP",
        "X-Real-IP",
        "X-Forwarded-For",
        "X-Client-IP",
    ):

        value = request.headers.get(header)

        if value:
            return value.split(",")[0].strip()

    return request.remote_addr or ""


def is_bot(user_agent):

    ua = (user_agent or "").lower()

    return any(
        hint in ua
        for hint in BOT_HINTS
    )


# =========================================================
# GEOLOOKUP
# =========================================================

def _fetch_json(url, timeout=1.5):

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "SmartLink/5.0"
        }
    )

    with urllib.request.urlopen(
        req,
        timeout=timeout
    ) as response:

        return json.loads(
            response.read().decode("utf-8")
        )


def get_country(ip, user_agent=""):

    try:

        header_code = (
            request.headers.get("CF-IPCountry")
            or request.headers.get("CloudFront-Viewer-Country")
            or request.headers.get("X-AppEngine-Country")
        )

        if header_code:

            code = header_code.strip().upper()

            if code not in ("XX", "T1", "ZZ"):

                return COUNTRY_NAMES.get(
                    code,
                    code
                )

        if not ip or ip in ("127.0.0.1", "::1"):
            return "Local"

        if is_bot(user_agent):
            return "Bot / Preview"

        lookups = [

            (
                "https://ipwho.is/" + ip,
                lambda d:
                    d.get("country")
                    if d.get("success")
                    else None,
            ),

            (
                "https://ipapi.co/" + ip + "/json/",
                lambda d:
                    None
                    if d.get("error")
                    else d.get("country_name"),
            ),

            (
                "http://ip-api.com/json/"
                + ip
                + "?fields=status,country",
                lambda d:
                    d.get("country")
                    if d.get("status") == "success"
                    else None,
            ),
        ]

        for lookup_url, picker in lookups:

            try:

                data = _fetch_json(lookup_url)

                country = picker(data)

                if country:
                    return str(country)

            except Exception:
                continue

        return "Unknown"

    except Exception:
        return "Unknown"


# =========================================================
# DEVICE
# =========================================================

def get_device(user_agent):

    ua = (user_agent or "").lower()

    if is_bot(user_agent):
        return "Bot / Preview"

    if "ipad" in ua:
        return "iPad"

    if "iphone" in ua:
        return "iPhone"

    if "android" in ua and "mobile" in ua:
        return "Android"

    if "android" in ua:
        return "Android Tablet"

    if "windows" in ua:
        return "Windows PC"

    if "macintosh" in ua or "mac os" in ua:
        return "Mac"

    if "linux" in ua:
        return "Linux"

    return "Others"


def get_operating_system(user_agent):

    ua = (user_agent or "").lower()

    if is_bot(user_agent):
        return "Bot"

    if "iphone" in ua or "ipad" in ua:
        return "iOS"

    if "android" in ua:
        return "Android"

    if "windows" in ua:
        return "Windows"

    if "mac os" in ua or "macintosh" in ua:
        return "macOS"

    if "linux" in ua:
        return "Linux"

    return "Others"


def get_browser(user_agent):

    ua = (user_agent or "").lower()

    if is_bot(user_agent):
        return "Bot / Crawler"

    if "edg/" in ua:
        return "Microsoft Edge"

    if "opr/" in ua or "opera" in ua:
        return "Opera"

    if "firefox/" in ua or "fxios" in ua:
        return "Mozilla Firefox"

    if "chrome/" in ua or "crios" in ua:
        return "Google Chrome"

    if "safari/" in ua and "chrome" not in ua:
        return "Safari"

    return "Others"


# =========================================================
# HELPERS
# =========================================================

def hash_ip(ip):

    return hashlib.sha256(
        (ip or "").encode("utf-8")
    ).hexdigest()


def format_dt(dt):

    if not dt:
        return "—"

    try:
        return dt.strftime(
            "%d %b %Y  ·  %I:%M %p"
        )
    except Exception:
        return str(dt)


def is_safe_next_url(value):

    if not value:
        return False

    value = value.strip()

    if not value.startswith("/"):
        return False

    if value.startswith("//"):
        return False

    parsed = urlparse(value)

    if parsed.scheme or parsed.netloc:
        return False

    return True


# =========================================================
# CURRENT USER
# =========================================================

def current_user():

    uid = session.get("user_id")

    if not uid:
        return None

    try:

        # Convert session value back to UUID.
        # This is important because database IDs are UUID.
        try:
            uid = uuid.UUID(str(uid))
        except (ValueError, TypeError, AttributeError):
            session.clear()
            return None

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        id,
                        name,
                        email,
                        is_admin
                    FROM users
                    WHERE id = %s
                    """,
                    (uid,)
                )

                row = cur.fetchone()

        if not row:

            session.clear()
            return None

        user_id = row[0]
        name = row[1]
        email = row[2]
        database_admin = bool(row[3])

        environment_admin = bool(
            ADMIN_EMAIL
            and email
            and email.strip().lower() == ADMIN_EMAIL
        )

        return {
            "id": user_id,
            "name": name,
            "email": email,
            "is_admin": (
                database_admin
                or environment_admin
            ),
        }

    except Exception as exc:

        print(
            "CURRENT USER ERROR:",
            repr(exc)
        )

        return None


# =========================================================
# AUTH DECORATORS
# =========================================================

def login_required(view):

    @wraps(view)
    def wrapped(*args, **kwargs):

        if not current_user():

            next_path = request.path

            if request.query_string:

                next_path += (
                    "?"
                    + request.query_string.decode(
                        "utf-8",
                        errors="ignore"
                    )
                )

            return redirect(
                url_for(
                    "signin",
                    next=next_path
                )
            )

        return view(*args, **kwargs)

    return wrapped


def admin_required(view):

    @wraps(view)
    def wrapped(*args, **kwargs):

        user = current_user()

        if not user:

            return redirect(
                url_for(
                    "signin",
                    next=request.path
                )
            )

        if not user["is_admin"]:
            abort(403)

        return view(*args, **kwargs)

    return wrapped


# =========================================================
# CSS
# =========================================================

CSS = """
:root{
--ink:#08090c;
--panel:#12141a;
--raised:#1b1f28;
--line:#2c313c;
--gold:#d4af37;
--ivory:#f4efe4;
--muted:#9a9386;
--danger:#f87171
}

*{
box-sizing:border-box;
margin:0;
padding:0
}

html,body{
min-height:100%
}

body{
font-family:Outfit,system-ui,sans-serif;
background:
radial-gradient(
ellipse at top,
rgba(212,175,55,.08),
transparent 55%
),
var(--ink);
color:var(--ivory)
}

a{
color:inherit
}

.wrap{
max-width:1100px;
margin:0 auto;
padding:0 20px
}

header{
border-bottom:1px solid var(--line);
position:sticky;
top:0;
z-index:20;
background:rgba(8,9,12,.88);
backdrop-filter:blur(12px)
}

.nav{
display:flex;
align-items:center;
justify-content:space-between;
gap:16px;
padding:16px 0;
flex-wrap:wrap
}

.brand{
display:flex;
align-items:center;
gap:12px;
text-decoration:none
}

.mark{
width:36px;
height:36px;
border:1px solid rgba(212,175,55,.4);
border-radius:8px;
display:grid;
place-items:center;
color:var(--gold)
}

.brand b{
display:block;
font-family:"Cormorant Garamond",serif;
font-size:20px;
font-weight:600
}

.brand small{
display:block;
letter-spacing:.22em;
text-transform:uppercase;
font-size:10px;
color:var(--muted)
}

.menu{
display:flex;
flex-wrap:wrap;
gap:4px;
align-items:center
}

.menu a,
.menu button{
background:none;
border:0;
color:var(--muted);
padding:10px 12px;
border-radius:8px;
text-decoration:none;
font-size:14px;
cursor:pointer
}

.menu a.active,
.menu a:hover,
.menu button:hover{
color:var(--ivory);
background:var(--raised)
}

.menu .gold{
color:var(--gold)
}

main{
padding:40px 0 72px
}

h1,h2,h3{
font-family:"Cormorant Garamond",serif;
font-weight:600
}

.kicker{
color:var(--gold);
letter-spacing:.28em;
text-transform:uppercase;
font-size:11px
}

.hero h1{
font-size:clamp(36px,6vw,58px);
line-height:.95;
margin:12px 0 16px
}

.hero p{
color:var(--muted);
max-width:520px;
line-height:1.6
}

form.row{
display:flex;
gap:12px;
margin-top:32px
}

form.stack{
display:flex;
flex-direction:column;
gap:14px;
margin-top:24px;
max-width:420px
}

form.stack label{
font-size:12px;
letter-spacing:.12em;
text-transform:uppercase;
color:var(--muted)
}

input{
width:100%;
min-height:52px;
border:1px solid var(--line);
background:var(--panel);
color:var(--ivory);
border-radius:10px;
padding:0 16px;
font:inherit;
outline:none
}

input:focus{
border-color:var(--gold)
}

.btn{
min-height:52px;
border:0;
border-radius:10px;
background:var(--gold);
color:var(--ink);
font-weight:700;
padding:0 22px;
cursor:pointer;
text-decoration:none;
display:inline-flex;
align-items:center;
justify-content:center;
white-space:nowrap
}

.stats{
display:grid;
grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
gap:12px;
margin:28px 0
}

.stat,
.card,
.panel{
background:var(--panel);
border:1px solid var(--line);
border-radius:16px
}

.stat{
padding:22px
}

.stat b{
display:block;
font-family:"Cormorant Garamond",serif;
font-size:36px;
color:var(--gold)
}

.stat span{
color:var(--muted);
font-size:12px;
letter-spacing:.16em;
text-transform:uppercase
}

.card{
overflow:hidden
}

.card-h{
padding:20px 22px;
border-bottom:1px solid var(--line)
}

.card-h p{
color:var(--muted);
font-size:14px;
margin-top:4px
}

.table-wrap{
overflow-x:auto
}

table{
width:100%;
border-collapse:collapse;
min-width:720px
}

th{
text-align:left;
font-size:11px;
letter-spacing:.14em;
text-transform:uppercase;
color:var(--muted);
font-weight:500;
background:var(--raised);
padding:12px 18px
}

td{
padding:14px 18px;
border-top:1px solid var(--line);
font-size:14px;
vertical-align:middle
}

.gold{
color:var(--gold);
font-weight:700;
text-decoration:none
}

.muted{
color:var(--muted)
}

.err{
color:var(--danger);
font-size:14px;
margin-top:10px
}

.tag{
display:inline-block;
background:var(--raised);
color:var(--gold);
padding:4px 10px;
border-radius:6px;
font-size:13px;
font-weight:600
}

.grid3{
display:grid;
gap:12px;
grid-template-columns:1fr;
margin:22px 0
}

.panel{
padding:20px
}

.chip{
display:flex;
justify-content:space-between;
gap:12px;
padding:8px 0;
font-size:14px;
border-bottom:1px solid var(--line)
}

.chip:last-child{
border:0
}

footer{
border-top:1px solid var(--line);
padding:22px 0;
color:var(--muted);
font-size:14px
}

.foot{
display:flex;
justify-content:space-between;
gap:12px;
flex-wrap:wrap
}

.modal-bg{
position:fixed;
inset:0;
background:rgba(8,9,12,.82);
display:none;
place-items:center;
padding:16px;
z-index:50
}

.modal-bg.open{
display:grid
}

.modal{
width:min(440px,100%);
background:var(--panel);
border:1px solid var(--line);
border-radius:16px;
padding:24px
}

.tg{
display:block;
margin-top:18px;
padding:18px;
border:1px solid rgba(212,175,55,.4);
border-radius:12px;
text-decoration:none;
background:var(--raised)
}

.tg b{
display:block;
font-family:"Cormorant Garamond",serif;
font-size:28px
}

.tg span{
color:var(--gold)
}

.auth-box{
max-width:460px;
margin:0 auto
}

@media(min-width:800px){
.grid3{
grid-template-columns:1fr 1fr 1fr
}
}

@media(max-width:700px){
form.row{
flex-direction:column
}

.btn{
width:100%
}
}
"""


# =========================================================
# LAYOUT
# =========================================================

def layout(title, body, active=""):

    user = current_user()

    def nav(href, key, label):

        cls = "active" if active == key else ""

        return (
            f'<a class="{cls}" href="{href}">{label}</a>'
        )

    if user:

        admin_link = ""

        if user["is_admin"]:
            admin_link = nav(
                "/admin",
                "admin",
                "Admin"
            )

        auth_links = (
            nav("/", "home", "Create")
            +
            nav("/dashboard", "dashboard", "Dashboard")
            +
            nav("/live-console", "live", "Live")
            +
            admin_link
            +
            (
                '<span class="muted" '
                'style="padding:0 8px;font-size:13px">'
                + html.escape(user["name"])
                + "</span>"
            )
            +
            '<a href="/signout">Sign out</a>'
        )

    else:

        auth_links = (
            nav("/signin", "signin", "Sign in")
            +
            nav("/signup", "signup", "Sign up")
        )

    return f"""<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="UTF-8">

<meta
name="viewport"
content="width=device-width, initial-scale=1"
>

<title>{html.escape(title)}</title>

<link
href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=Outfit:wght@400;500;600;700&display=swap"
rel="stylesheet"
>

<style>
{CSS}
</style>

</head>

<body>

<header>

<div class="wrap nav">

<a class="brand" href="/">

<span class="mark">◆</span>

<span>

<b>SmartLink</b>

<small>Private workspace</small>

</span>

</a>

<nav class="menu">

{auth_links}

<button
type="button"
class="gold"
onclick="openSupport()"
>
Support
</button>

</nav>

</div>

</header>

<main>

<div class="wrap">

{body}

</div>

</main>

<footer>

<div class="wrap foot">

<span>SmartLink</span>

<button
type="button"
class="gold"
style="background:none;border:0;cursor:pointer;font:inherit;color:var(--gold)"
onclick="openSupport()"
>
Support · Telegram
</button>

</div>

</footer>

<div
class="modal-bg"
id="supportModal"
onclick="if(event.target===this)closeSupport()"
>

<div class="modal">

<p class="kicker">Support</p>

<h2 style="font-size:32px;margin:8px 0 10px">
Direct line
</h2>

<p class="muted">
Tap the name to open Telegram.
</p>

<a
class="tg"
href="{SUPPORT_URL}"
target="_blank"
rel="noopener noreferrer"
>

<b>{SUPPORT_NAME}</b>

<span>{SUPPORT_HANDLE}</span>

<p
class="muted"
style="margin-top:10px;letter-spacing:.16em;text-transform:uppercase;font-size:11px"
>
Open Telegram →
</p>

</a>

<p style="margin-top:14px">

<button
type="button"
onclick="closeSupport()"
style="background:none;border:0;color:var(--muted);cursor:pointer"
>
Close
</button>

</p>

</div>

</div>

<script>

function openSupport(){{
    document
        .getElementById("supportModal")
        .classList.add("open");
}}

function closeSupport(){{
    document
        .getElementById("supportModal")
        .classList.remove("open");
}}

</script>

</body>

</html>
"""


# =========================================================
# SIGN UP
# =========================================================

@app.route("/signup", methods=["GET", "POST"])
def signup():

    if current_user():
        return redirect("/")

    error = ""

    if request.method == "POST":

        name = (
            request.form.get("name") or ""
        ).strip()

        email = (
            request.form.get("email") or ""
        ).strip().lower()

        password = (
            request.form.get("password") or ""
        )

        if len(name) < 2:

            error = "Name is too short."

        elif "@" not in email or "." not in email:

            error = "Enter a valid email."

        elif len(password) < 6:

            error = "Password must be at least 6 characters."

        else:

            is_admin = bool(
                ADMIN_EMAIL
                and email == ADMIN_EMAIL
            )

            try:

                with get_db() as conn:

                    with conn.cursor() as cur:

                        cur.execute(
                            """
                            SELECT id
                            FROM users
                            WHERE LOWER(email) = %s
                            """,
                            (email,)
                        )

                        if cur.fetchone():

                            error = (
                                "Email already registered. "
                                "Please sign in."
                            )

                        else:

                            # UUID generated in Python.
                            new_user_id = uuid.uuid4()

                            cur.execute(
                                """
                                INSERT INTO users
                                (
                                    id,
                                    name,
                                    email,
                                    password_hash,
                                    is_admin
                                )
                                VALUES
                                (%s,%s,%s,%s,%s)
                                RETURNING id
                                """,
                                (
                                    new_user_id,
                                    name,
                                    email,
                                    generate_password_hash(password),
                                    is_admin,
                                ),
                            )

                            uid = cur.fetchone()[0]

                            conn.commit()

                if not error:

                    session.clear()

                    session["user_id"] = str(uid)
                    session.permanent = True

                    return redirect("/")

            except Exception as exc:

                print(
                    "SIGNUP ERROR:",
                    repr(exc)
                )

                error = (
                    "Signup failed. "
                    "Please try again."
                )

    err_html = (
        f"<p class='err'>{html.escape(error)}</p>"
        if error
        else ""
    )

    body = f"""
<div class="auth-box">

<p class="kicker">Account</p>

<h1>Create your workspace</h1>

<p class="muted" style="margin-top:8px">
Your links stay private — only you can see them.
</p>

<form class="stack" method="POST" action="/signup">

<div>

<label>Name</label>

<input
type="text"
name="name"
required
minlength="2"
placeholder="Your name"
>

</div>

<div>

<label>Email</label>

<input
type="email"
name="email"
required
placeholder="you@email.com"
>

</div>

<div>

<label>Password</label>

<input
type="password"
name="password"
required
minlength="6"
placeholder="Min 6 characters"
>

</div>

<button class="btn" type="submit">
Sign up
</button>

</form>

{err_html}

<p class="muted" style="margin-top:18px">

Already have an account?

<a class="gold" href="/signin">
Sign in
</a>

</p>

</div>
"""

    return layout(
        "Sign up · SmartLink",
        body,
        "signup"
    )


# =========================================================
# SIGN IN
# =========================================================

@app.route("/signin", methods=["GET", "POST"])
def signin():

    if current_user():
        return redirect("/")

    error = ""

    next_url = (
        request.args.get("next")
        or request.form.get("next")
        or "/"
    )

    if not is_safe_next_url(next_url):
        next_url = "/"

    if request.method == "POST":

        email = (
            request.form.get("email") or ""
        ).strip().lower()

        password = (
            request.form.get("password") or ""
        )

        try:

            with get_db() as conn:

                with conn.cursor() as cur:

                    cur.execute(
                        """
                        SELECT
                            id,
                            password_hash
                        FROM users
                        WHERE LOWER(email) = %s
                        """,
                        (email,)
                    )

                    row = cur.fetchone()

            if (
                not row
                or not check_password_hash(
                    row[1],
                    password
                )
            ):

                error = "Invalid email or password."

            else:

                session.clear()

                session["user_id"] = str(row[0])
                session.permanent = True

                return redirect(next_url)

        except Exception as exc:

            print(
                "SIGNIN ERROR:",
                repr(exc)
            )

            error = (
                "Sign in failed. "
                "Please try again."
            )

    err_html = (
        f"<p class='err'>{html.escape(error)}</p>"
        if error
        else ""
    )

    safe_next = html.escape(
        next_url,
        quote=True
    )

    body = f"""
<div class="auth-box">

<p class="kicker">Welcome back</p>

<h1>Sign in</h1>

<form class="stack" method="POST" action="/signin">

<input
type="hidden"
name="next"
value="{safe_next}"
>

<div>

<label>Email</label>

<input
type="email"
name="email"
required
placeholder="you@email.com"
>

</div>

<div>

<label>Password</label>

<input
type="password"
name="password"
required
placeholder="Your password"
>

</div>

<button class="btn" type="submit">
Sign in
</button>

</form>

{err_html}

<p class="muted" style="margin-top:18px">

New here?

<a class="gold" href="/signup">
Create account
</a>

</p>

</div>
"""

    return layout(
        "Sign in · SmartLink",
        body,
        "signin"
    )


# =========================================================
# SIGN OUT
# =========================================================

@app.route("/signout")
def signout():

    session.clear()

    return redirect("/signin")


# =========================================================
# HOME
# =========================================================

@app.route("/")
@login_required
def home():

    body = """
<section class="hero">

<p class="kicker">
Your private links
</p>

<h1>
Create a short link.
</h1>

<p>
Only you can see the links you create.
Clicks record country, device, OS,
browser, date and time.
</p>

<form
class="row"
method="POST"
action="/create"
>

<input
type="url"
name="url"
placeholder="https://example.com/your-page"
required
>

<button
class="btn"
type="submit"
>
Create link
</button>

</form>

</section>
"""

    return layout(
        "SmartLink",
        body,
        "home"
    )


# =========================================================
# CREATE LINK
# =========================================================

@app.route("/create", methods=["POST"])
@login_required
def create_link():

    user = current_user()

    if not user:
        return redirect(
            url_for(
                "signin",
                next="/"
            )
        )

    try:

        original_url = (
            request.form.get("url") or ""
        ).strip()

        parsed = urlparse(original_url)

        if (
            parsed.scheme not in ("http", "https")
            or not parsed.netloc
        ):

            return (
                "Invalid URL",
                400
            )

        # Generate short code.
        short_code = generate_short_code()

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO links
                    (
                        user_id,
                        short_code,
                        original_url,
                        clicks
                    )
                    VALUES
                    (%s,%s,%s,0)
                    RETURNING short_code
                    """,
                    (
                        user["id"],
                        short_code,
                        original_url,
                    ),
                )

                created_code = cur.fetchone()[0]

            conn.commit()

        short_url = (
            request.host_url
            + str(created_code)
        )

        safe_url = html.escape(short_url)

        body = f"""
<p class="kicker">
Ready
</p>

<h1>
Link created
</h1>

<div
class="card"
style="margin-top:24px;padding:24px"
>

<p class="muted">
Your private SmartLink
</p>

<p
style="margin:10px 0 18px;word-break:break-all"
>

<a
class="gold"
href="{safe_url}"
>
{safe_url}
</a>

</p>

<a
class="btn"
href="/dashboard"
>
Open dashboard
</a>

</div>
"""

        return layout(
            "Link created · SmartLink",
            body,
            "home"
        )

    except Exception as exc:

        print("========== CREATE LINK ERROR ==========")
        print(repr(exc))
        print("=======================================")

        return (
            "Unable to create link. Please try again.",
            500
        )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
@login_required
def dashboard():

    user = current_user()

    if not user:
        return redirect("/signin")

    try:

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        short_code,
                        original_url,
                        clicks,
                        created_at
                    FROM links
                    WHERE user_id = %s
                    ORDER BY id DESC
                    """,
                    (user["id"],)
                )

                links = cur.fetchall()

                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM links
                    WHERE user_id = %s
                    """,
                    (user["id"],)
                )

                total_links = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT COALESCE(SUM(clicks),0)
                    FROM links
                    WHERE user_id = %s
                    """,
                    (user["id"],)
                )

                total_clicks = cur.fetchone()[0]

    except Exception as exc:

        print(
            "DASHBOARD ERROR:",
            repr(exc)
        )

        return (
            "Dashboard error. Please try again.",
            500
        )

    rows = ""

    for short, original_url, clicks, created in links:

        safe_url = html.escape(original_url)

        display = (
            safe_url
            if len(original_url) < 58
            else html.escape(
                original_url[:55] + "..."
            )
        )

        safe_short = html.escape(str(short))

        rows += f"""
<tr>

<td>

<a
class="gold"
href="/{safe_short}"
>
/{safe_short}
</a>

</td>

<td
class="muted"
title="{safe_url}"
>
{display}
</td>

<td>
{int(clicks)}
</td>

<td class="muted">
{format_dt(created)}
</td>

<td>

<a
class="gold"
href="/analytics/{safe_short}"
>
View A–Z
</a>

</td>

</tr>
"""

    if not rows:

        rows = """
<tr>

<td
colspan="5"
class="muted"
style="text-align:center;padding:48px"
>
No links yet.
</td>

</tr>
"""

    body = f"""
<p class="kicker">
Only your data
</p>

<h1>
Dashboard
</h1>

<div class="stats">

<div class="stat">

<b>{total_links}</b>

<span>Your links</span>

</div>

<div class="stat">

<b>{total_clicks}</b>

<span>Your clicks</span>

</div>

</div>

<div class="card">

<div class="card-h">

<h2>
Your SmartLinks
</h2>

<p>
Other users cannot see these links.
</p>

</div>

<div class="table-wrap">

<table>

<thead>

<tr>

<th>Short link</th>
<th>Destination</th>
<th>Clicks</th>
<th>Created</th>
<th>Details</th>

</tr>

</thead>

<tbody>

{rows}

</tbody>

</table>

</div>

</div>
"""

    return layout(
        "Dashboard · SmartLink",
        body,
        "dashboard"
    )


# =========================================================
# ANALYTICS
# =========================================================

@app.route("/analytics/<short_code>")
@login_required
def analytics(short_code):

    user = current_user()

    if not user:
        return redirect("/signin")

    try:

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        id,
                        short_code,
                        original_url,
                        clicks,
                        created_at,
                        user_id
                    FROM links
                    WHERE short_code = %s
                    """,
                    (short_code,)
                )

                link = cur.fetchone()

                if not link:
                    abort(404)

                (
                    link_id,
                    sc,
                    original_url,
                    clicks,
                    created_at,
                    owner_id,
                ) = link

                if (
                    owner_id != user["id"]
                    and not user["is_admin"]
                ):
                    abort(403)

                cur.execute(
                    """
                    SELECT
                        country,
                        device,
                        operating_system,
                        browser,
                        clicked_at
                    FROM click_logs
                    WHERE link_id = %s
                    ORDER BY id DESC
                    LIMIT 200
                    """,
                    (link_id,)
                )

                click_rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT country, COUNT(*)
                    FROM click_logs
                    WHERE link_id = %s
                    GROUP BY country
                    ORDER BY COUNT(*) DESC
                    LIMIT 8
                    """,
                    (link_id,)
                )

                top_countries = cur.fetchall()

                cur.execute(
                    """
                    SELECT device, COUNT(*)
                    FROM click_logs
                    WHERE link_id = %s
                    GROUP BY device
                    ORDER BY COUNT(*) DESC
                    LIMIT 8
                    """,
                    (link_id,)
                )

                top_devices = cur.fetchall()

                cur.execute(
                    """
                    SELECT browser, COUNT(*)
                    FROM click_logs
                    WHERE link_id = %s
                    GROUP BY browser
                    ORDER BY COUNT(*) DESC
                    LIMIT 8
                    """,
                    (link_id,)
                )

                top_browsers = cur.fetchall()

    except Exception as exc:

        print(
            "ANALYTICS ERROR:",
            repr(exc)
        )

        return (
            "Analytics error. Please try again.",
            500
        )

    def chips(items):

        if not items:

            return (
                '<p class="muted">No data yet</p>'
            )

        output = ""

        for name, count in items:

            output += f"""
<div class="chip">

<span>
{html.escape(str(name or "Unknown"))}
</span>

<b class="gold">
{int(count)}
</b>

</div>
"""

        return output

    rows = ""

    for (
        country,
        device,
        os_name,
        browser,
        clicked_at,
    ) in click_rows:

        rows += f"""
<tr>

<td>

<span class="tag">
{html.escape(country or "Unknown")}
</span>

</td>

<td>
{html.escape(device or "Others")}
</td>

<td>
{html.escape(os_name or "Others")}
</td>

<td>
{html.escape(browser or "Others")}
</td>

<td class="muted">
{format_dt(clicked_at)}
</td>

</tr>
"""

    if not rows:

        rows = """
<tr>

<td
colspan="5"
class="muted"
style="text-align:center;padding:48px"
>
No clicks yet.
</td>

</tr>
"""

    body = f"""
<p>

<a
class="gold"
href="/dashboard"
>
← Dashboard
</a>

</p>

<h1 style="margin-top:12px">
/{html.escape(str(sc))}
</h1>

<p
class="muted"
style="margin:8px 0 16px;word-break:break-all"
>
{html.escape(original_url)}
</p>

<p
style="font-family:'Cormorant Garamond',serif;font-size:48px;color:var(--gold)"
>

{int(clicks)}

<span
class="muted"
style="font-size:22px"
>
clicks
</span>

</p>

<p class="muted">
Created {format_dt(created_at)}
</p>

<div class="grid3">

<div class="panel">

<p class="kicker">
Countries
</p>

{chips(top_countries)}

</div>

<div class="panel">

<p class="kicker">
Devices
</p>

{chips(top_devices)}

</div>

<div class="panel">

<p class="kicker">
Browsers
</p>

{chips(top_browsers)}

</div>

</div>

<div class="card">

<div class="card-h">

<h2>
Click log
</h2>

<p>
Country · device · OS · browser · date · time
</p>

</div>

<div class="table-wrap">

<table>

<thead>

<tr>

<th>Country</th>
<th>Device</th>
<th>OS</th>
<th>Browser</th>
<th>Date & time</th>

</tr>

</thead>

<tbody>

{rows}

</tbody>

</table>

</div>

</div>
"""

    return layout(
        f"Analytics · /{sc}",
        body,
        "dashboard"
    )


# =========================================================
# LIVE CLICKS API
# =========================================================

@app.route("/api/live-clicks")
@login_required
def live_clicks():

    user = current_user()

    if not user:
        return jsonify({
            "error": "Authentication required"
        }), 401

    try:

        with get_db() as conn:

            with conn.cursor() as cur:

                if user["is_admin"]:

                    cur.execute(
                        """
                        SELECT
                            id,
                            short_code,
                            country,
                            device,
                            operating_system,
                            browser,
                            clicked_at
                        FROM click_logs
                        ORDER BY id DESC
                        LIMIT 120
                        """
                    )

                else:

                    cur.execute(
                        """
                        SELECT
                            cl.id,
                            cl.short_code,
                            cl.country,
                            cl.device,
                            cl.operating_system,
                            cl.browser,
                            cl.clicked_at
                        FROM click_logs cl
                        JOIN links l
                            ON l.id = cl.link_id
                        WHERE l.user_id = %s
                        ORDER BY cl.id DESC
                        LIMIT 120
                        """,
                        (user["id"],)
                    )

                rows = cur.fetchall()

        data = []

        for row in rows:

            data.append({
                "id": row[0],
                "short_code": row[1],
                "country": row[2] or "Unknown",
                "device": row[3] or "Others",
                "os": row[4] or "Others",
                "browser": row[5] or "Others",
                "clicked_at": (
                    row[6].isoformat()
                    if row[6]
                    else None
                ),
            })

        return jsonify(data)

    except Exception as exc:

        print(
            "LIVE CLICKS ERROR:",
            repr(exc)
        )

        return jsonify({
            "error": "Unable to load live clicks"
        }), 500


# =========================================================
# LIVE CONSOLE
# =========================================================

@app.route("/live-console")
@login_required
def live_console():

    body = """
<p class="kicker">
Live
</p>

<h1>
Click console
</h1>

<p
class="muted"
style="margin:8px 0 22px"
>
Only your links (admin sees all).
</p>

<div class="card">

<div style="padding:20px">

<input
id="search"
placeholder="Search…"
>

</div>

<div class="table-wrap">

<table>

<thead>

<tr>

<th>Date & time</th>
<th>Link</th>
<th>Country</th>
<th>Device</th>
<th>OS</th>
<th>Browser</th>

</tr>

</thead>

<tbody id="events">

<tr>

<td
colspan="6"
class="muted"
style="text-align:center;padding:48px"
>
Waiting…
</td>

</tr>

</tbody>

</table>

</div>

</div>

<script>

let events = [];

function escapeHtml(value) {{

    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}}

function renderEvents() {{

    const search =
        document
        .getElementById("search")
        .value
        .toLowerCase();

    const body =
        document.getElementById("events");

    const filtered =
        events.filter(event => {{

            const text =
                event.short_code + " " +
                event.country + " " +
                event.device + " " +
                event.os + " " +
                event.browser;

            return text
                .toLowerCase()
                .includes(search);
        }});

    if (!filtered.length) {{

        body.innerHTML =
            "<tr>" +
            "<td colspan='6' class='muted' " +
            "style='text-align:center;padding:48px'>" +
            "No matching events" +
            "</td></tr>";

        return;
    }}

    body.innerHTML =
        filtered.map(event => {{

            const time =
                event.clicked_at
                ? new Date(
                    event.clicked_at
                ).toLocaleString()
                : "—";

            const code =
                escapeHtml(event.short_code);

            return `
<tr>

<td class="muted">
${escapeHtml(time)}
</td>

<td>
<a
class="gold"
href="/analytics/${code}"
>
/${code}
</a>
</td>

<td>
<span class="tag">
${escapeHtml(event.country)}
</span>
</td>

<td>
${escapeHtml(event.device)}
</td>

<td>
${escapeHtml(event.os)}
</td>

<td>
${escapeHtml(event.browser)}
</td>

</tr>
`;

        }).join("");
}}

async function loadEvents() {{

    try {{

        const response =
            await fetch(
                "/api/live-clicks",
                {{
                    cache: "no-store"
                }}
            );

        if (!response.ok)
            return;

        const data =
            await response.json();

        if (
            data &&
            !Array.isArray(data)
        )
            return;

        events = data;

        renderEvents();

    }} catch (error) {{

        // Temporary polling errors are ignored.

    }}
}}

document
    .getElementById("search")
    .addEventListener(
        "input",
        renderEvents
    );

loadEvents();

setInterval(
    loadEvents,
    2000
);

</script>
"""

    return layout(
        "Live Console · SmartLink",
        body,
        "live"
    )


# =========================================================
# ADMIN PANEL
# =========================================================

@app.route("/admin")
@admin_required
def admin_panel():

    try:

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    "SELECT COUNT(*) FROM users"
                )

                total_users = cur.fetchone()[0]

                cur.execute(
                    "SELECT COUNT(*) FROM links"
                )

                total_links = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT COALESCE(SUM(clicks),0)
                    FROM links
                    """
                )

                total_clicks = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT
                        u.id,
                        u.name,
                        u.email,
                        u.is_admin,
                        u.created_at,
                        COUNT(l.id),
                        COALESCE(SUM(l.clicks),0)
                    FROM users u
                    LEFT JOIN links l
                        ON l.user_id = u.id
                    GROUP BY
                        u.id,
                        u.name,
                        u.email,
                        u.is_admin,
                        u.created_at
                    ORDER BY u.created_at DESC
                    """
                )

                users = cur.fetchall()

                cur.execute(
                    """
                    SELECT
                        l.short_code,
                        l.original_url,
                        l.clicks,
                        l.created_at,
                        u.email
                    FROM links l
                    LEFT JOIN users u
                        ON u.id = l.user_id
                    ORDER BY l.id DESC
                    LIMIT 100
                    """
                )

                links = cur.fetchall()

    except Exception as exc:

        print(
            "ADMIN ERROR:",
            repr(exc)
        )

        return (
            "Admin error. Please try again.",
            500
        )

    user_rows = ""

    for (
        uid,
        name,
        email,
        is_admin,
        created,
        link_count,
        click_count,
    ) in users:

        badge = "Admin" if is_admin else "User"

        user_rows += f"""
<tr>

<td>
{html.escape(str(uid))}
</td>

<td>
{html.escape(name or "")}
</td>

<td>
{html.escape(email or "")}
</td>

<td>

<span class="tag">
{badge}
</span>

</td>

<td>
{int(link_count)}
</td>

<td>
{int(click_count)}
</td>

<td class="muted">
{format_dt(created)}
</td>

</tr>
"""

    link_rows = ""

    for (
        short,
        original_url,
        clicks,
        created,
        email,
    ) in links:

        owner = html.escape(email or "—")

        safe_url = html.escape(original_url)

        display = (
            safe_url
            if len(original_url) < 40
            else html.escape(
                original_url[:37] + "..."
            )
        )

        safe_short = html.escape(str(short))

        link_rows += f"""
<tr>

<td>

<a
class="gold"
href="/analytics/{safe_short}"
>
/{safe_short}
</a>

</td>

<td class="muted">
{display}
</td>

<td>
{int(clicks)}
</td>

<td>
{owner}
</td>

<td class="muted">
{format_dt(created)}
</td>

</tr>
"""

    if not user_rows:

        user_rows = """
<tr>

<td
colspan="7"
class="muted"
style="text-align:center;padding:32px"
>
No users
</td>

</tr>
"""

    if not link_rows:

        link_rows = """
<tr>

<td
colspan="5"
class="muted"
style="text-align:center;padding:32px"
>
No links
</td>

</tr>
"""

    body = f"""
<p class="kicker">
Admin
</p>

<h1>
Control panel
</h1>

<div class="stats">

<div class="stat">

<b>{total_users}</b>

<span>Signups</span>

</div>

<div class="stat">

<b>{total_links}</b>

<span>All links</span>

</div>

<div class="stat">

<b>{total_clicks}</b>

<span>All clicks</span>

</div>

</div>

<div
class="card"
style="margin-bottom:24px"
>

<div class="card-h">

<h2>
Users
</h2>

<p>
Who signed up, when, and their totals
</p>

</div>

<div class="table-wrap">

<table>

<thead>

<tr>

<th>ID</th>
<th>Name</th>
<th>Email</th>
<th>Role</th>
<th>Links</th>
<th>Clicks</th>
<th>Joined</th>

</tr>

</thead>

<tbody>

{user_rows}

</tbody>

</table>

</div>

</div>

<div class="card">

<div class="card-h">

<h2>
Recent links (all users)
</h2>

<p>
Latest 100 across the platform
</p>

</div>

<div class="table-wrap">

<table>

<thead>

<tr>

<th>Short</th>
<th>Destination</th>
<th>Clicks</th>
<th>Owner</th>
<th>Created</th>

</tr>

</thead>

<tbody>

{link_rows}

</tbody>

</table>

</div>

</div>
"""

    return layout(
        "Admin · SmartLink",
        body,
        "admin"
    )


# =========================================================
# SUPPORT
# =========================================================

@app.route("/support")
def support():

    return redirect(SUPPORT_URL)


# =========================================================
# SHORT LINK
# =========================================================

@app.route("/<short_code>")
@login_required
def redirect_short_link(short_code):

    reserved = {
        "create",
        "dashboard",
        "analytics",
        "live-console",
        "health",
        "api",
        "support",
        "signup",
        "signin",
        "signout",
        "admin",
    }

    if short_code in reserved:
        abort(404)

    try:

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        id,
                        original_url
                    FROM links
                    WHERE short_code = %s
                    """,
                    (short_code,)
                )

                link = cur.fetchone()

    except Exception as exc:

        print(
            "SHORT LINK LOOKUP ERROR:",
            repr(exc)
        )

        return (
            "Service temporarily unavailable",
            503
        )

    if not link:
        abort(404)

    link_id, original_url = link

    try:

        user_agent = request.headers.get(
            "User-Agent",
            ""
        )

        ip = get_client_ip()

        country = get_country(
            ip,
            user_agent
        )

        device = get_device(
            user_agent
        )

        operating_system = get_operating_system(
            user_agent
        )

        browser = get_browser(
            user_agent
        )

        ip_hash_value = hash_ip(ip)

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    UPDATE links
                    SET clicks = clicks + 1
                    WHERE id = %s
                    """,
                    (link_id,)
                )

                cur.execute(
                    """
                    INSERT INTO click_logs
                    (
                        link_id,
                        short_code,
                        country,
                        device,
                        operating_system,
                        browser,
                        ip_hash
                    )
                    VALUES
                    (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        link_id,
                        short_code,
                        country,
                        device,
                        operating_system,
                        browser,
                        ip_hash_value,
                    )
                )

            conn.commit()

    except Exception as exc:

        print(
            "CLICK LOG ERROR:",
            repr(exc)
        )

        # Destination still works if analytics fails.

    return redirect(
        original_url,
        code=302
    )


# =========================================================
# HEALTH
# =========================================================

@app.route("/health")
def health():

    try:

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute("SELECT 1")

                result = cur.fetchone()[0]

        return jsonify({
            "status": "ok",
            "database": result == 1
        })

    except Exception as exc:

        print(
            "HEALTH ERROR:",
            repr(exc)
        )

        return jsonify({
            "status": "error",
            "database": False
        }), 500


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

try:

    setup_database()

    print(
        "======================================="
    )

    print(
        "SMARTLINK DATABASE READY"
    )

    print(
        "UUID USER SYSTEM ENABLED"
    )

    print(
        "======================================="
    )

except Exception as exc:

    print(
        "DATABASE SETUP FAILED:",
        repr(exc)
    )


# =========================================================
# LOCAL RUN
# =========================================================

if __name__ == "__main__":

    print(
        "SMARTLINK · "
        "UUID MULTI-USER + PRIVATE LINKS + ADMIN"
    )

    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "8080"
            )
        ),
        debug=False
    )