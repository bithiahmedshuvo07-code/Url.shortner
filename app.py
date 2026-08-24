import os
import random
import string
import hashlib
import html
import json
import urllib.request

import psycopg
from dotenv import load_dotenv
from flask import Flask, request, redirect, jsonify, abort

load_dotenv()

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not found in .env")

SUPPORT_NAME = "Shuvo Ahmed"
SUPPORT_HANDLE = "@Ahmed_shuvo_786"
SUPPORT_URL = "https://t.me/Ahmed_shuvo_786"

COUNTRY_NAMES = {
    "AF": "Afghanistan", "AL": "Albania", "DZ": "Algeria", "AR": "Argentina",
    "AU": "Australia", "AT": "Austria", "BD": "Bangladesh", "BE": "Belgium",
    "BR": "Brazil", "BG": "Bulgaria", "KH": "Cambodia", "CA": "Canada",
    "CL": "Chile", "CN": "China", "CO": "Colombia", "HR": "Croatia",
    "CZ": "Czechia", "DK": "Denmark", "EG": "Egypt", "EE": "Estonia",
    "ET": "Ethiopia", "FI": "Finland", "FR": "France", "DE": "Germany",
    "GH": "Ghana", "GR": "Greece", "HK": "Hong Kong", "HU": "Hungary",
    "IN": "India", "ID": "Indonesia", "IR": "Iran", "IQ": "Iraq",
    "IE": "Ireland", "IL": "Israel", "IT": "Italy", "JP": "Japan",
    "JO": "Jordan", "KE": "Kenya", "KW": "Kuwait", "LV": "Latvia",
    "LB": "Lebanon", "LY": "Libya", "LT": "Lithuania", "MY": "Malaysia",
    "MV": "Maldives", "MX": "Mexico", "MA": "Morocco", "MM": "Myanmar",
    "NP": "Nepal", "NL": "Netherlands", "NZ": "New Zealand", "NG": "Nigeria",
    "NO": "Norway", "OM": "Oman", "PK": "Pakistan", "PS": "Palestine",
    "PH": "Philippines", "PL": "Poland", "PT": "Portugal", "QA": "Qatar",
    "RO": "Romania", "RU": "Russia", "SA": "Saudi Arabia", "RS": "Serbia",
    "SG": "Singapore", "SK": "Slovakia", "ZA": "South Africa", "KR": "South Korea",
    "ES": "Spain", "LK": "Sri Lanka", "SE": "Sweden", "CH": "Switzerland",
    "TW": "Taiwan", "TH": "Thailand", "TR": "Turkey", "UA": "Ukraine",
    "AE": "United Arab Emirates", "GB": "United Kingdom", "UK": "United Kingdom",
    "US": "United States", "VN": "Vietnam", "YE": "Yemen",
}


def get_db():
    return psycopg.connect(DATABASE_URL, connect_timeout=10)


def setup_database():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    id BIGSERIAL PRIMARY KEY,
                    short_code TEXT UNIQUE NOT NULL,
                    original_url TEXT NOT NULL,
                    clicks BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS click_logs (
                    id BIGSERIAL PRIMARY KEY,
                    link_id BIGINT REFERENCES links(id) ON DELETE CASCADE,
                    short_code TEXT NOT NULL,
                    country TEXT DEFAULT 'Unknown',
                    device TEXT DEFAULT 'Others',
                    operating_system TEXT DEFAULT 'Others',
                    browser TEXT DEFAULT 'Others',
                    ip_hash TEXT,
                    clicked_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        conn.commit()


def generate_short_code(length=7):
    chars = string.ascii_letters + string.digits
    while True:
        code = "".join(random.choice(chars) for _ in range(length))
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM links WHERE short_code = %s", (code,))
                exists = cur.fetchone()
        if not exists:
            return code


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


def _fetch_json(url, timeout=2.2):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ShuvoAhmedSmartLink/3.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_country(ip):
    header_code = (
        request.headers.get("CF-IPCountry")
        or request.headers.get("CloudFront-Viewer-Country")
        or request.headers.get("X-AppEngine-Country")
    )
    if header_code:
        code = header_code.strip().upper()
        if code and code not in ("XX", "T1", "ZZ"):
            return COUNTRY_NAMES.get(code, code)

    if not ip or ip in ("127.0.0.1", "::1"):
        return "Local"

    lookups = [
        ("https://ipwho.is/" + ip, lambda d: d.get("country") if d.get("success") else None),
        ("https://ipapi.co/" + ip + "/json/", lambda d: None if d.get("error") else d.get("country_name")),
        ("http://ip-api.com/json/" + ip + "?fields=status,country", lambda d: d.get("country") if d.get("status") == "success" else None),
    ]
    for url, pick in lookups:
        try:
            data = _fetch_json(url)
            name = pick(data)
            if name:
                return str(name)
        except Exception:
            continue
    return "Unknown"


def get_device(user_agent):
    ua = (user_agent or "").lower()
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
    if "cros" in ua:
        return "ChromeOS"
    if "linux" in ua:
        return "Linux"
    return "Others"


def get_operating_system(user_agent):
    ua = (user_agent or "").lower()
    if "iphone" in ua or "ipad" in ua:
        return "iOS"
    if "android" in ua:
        return "Android"
    if "windows" in ua:
        return "Windows"
    if "mac os" in ua or "macintosh" in ua:
        return "macOS"
    if "cros" in ua:
        return "ChromeOS"
    if "linux" in ua:
        return "Linux"
    return "Others"


def get_browser(user_agent):
    ua = (user_agent or "").lower()
    if "edg/" in ua:
        return "Microsoft Edge"
    if "opr/" in ua or "opera" in ua:
        return "Opera"
    if "firefox/" in ua or "fxios" in ua:
        return "Mozilla Firefox"
    if "samsungbrowser" in ua:
        return "Samsung Internet"
    if "chrome/" in ua or "crios" in ua:
        return "Google Chrome"
    if "safari/" in ua and "chrome" not in ua:
        return "Safari"
    return "Others"


def hash_ip(ip):
    return hashlib.sha256((ip or "").encode("utf-8")).hexdigest()


def format_dt(dt):
    if not dt:
        return "—"
    try:
        return dt.strftime("%d %b %Y  ·  %I:%M %p")
    except Exception:
        return str(dt)


CSS = """
:root {
  --ink: #08090c;
  --panel: #12141a;
  --raised: #1b1f28;
  --line: #2c313c;
  --gold: #d4af37;
  --ivory: #f4efe4;
  --muted: #9a9386;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { min-height: 100%; }
body {
  font-family: Outfit, system-ui, sans-serif;
  background: radial-gradient(ellipse at top, rgba(212,175,55,.08), transparent 55%), var(--ink);
  color: var(--ivory);
}
a { color: inherit; }
.wrap { max-width: 1100px; margin: 0 auto; padding: 0 20px; }
header {
  border-bottom: 1px solid var(--line);
  position: sticky; top: 0; z-index: 20;
  background: rgba(8,9,12,.88);
  backdrop-filter: blur(12px);
}
.nav { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 0; }
.brand { display: flex; align-items: center; gap: 12px; text-decoration: none; }
.mark {
  width: 36px; height: 36px; border: 1px solid rgba(212,175,55,.4);
  border-radius: 8px; display: grid; place-items: center; color: var(--gold);
}
.brand b { display: block; font-family: "Cormorant Garamond", serif; font-size: 20px; font-weight: 600; }
.brand small { display: block; letter-spacing: .22em; text-transform: uppercase; font-size: 10px; color: var(--muted); }
.menu { display: flex; flex-wrap: wrap; gap: 4px; }
.menu a, .menu button {
  background: none; border: 0; color: var(--muted); padding: 10px 12px;
  border-radius: 8px; text-decoration: none; font-size: 14px; cursor: pointer;
}
.menu a.active, .menu a:hover, .menu button:hover { color: var(--ivory); background: var(--raised); }
.menu .gold { color: var(--gold); }
main { padding: 40px 0 72px; }
h1, h2, h3 { font-family: "Cormorant Garamond", serif; font-weight: 600; text-wrap: balance; }
.kicker { color: var(--gold); letter-spacing: .28em; text-transform: uppercase; font-size: 11px; }
.hero h1 { font-size: clamp(40px, 7vw, 64px); line-height: .95; margin: 12px 0 16px; }
.hero p { color: var(--muted); max-width: 520px; line-height: 1.6; }
form.row { display: flex; gap: 12px; margin-top: 32px; }
input[type=url], input[type=search], .search {
  width: 100%; min-height: 52px; border: 1px solid var(--line); background: var(--panel);
  color: var(--ivory); border-radius: 10px; padding: 0 16px; font: inherit; outline: none;
}
input:focus { border-color: var(--gold); }
.btn {
  min-height: 52px; border: 0; border-radius: 10px; background: var(--gold); color: var(--ink);
  font-weight: 700; padding: 0 22px; cursor: pointer; text-decoration: none; display: inline-flex;
  align-items: center; justify-content: center; white-space: nowrap;
}
.stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin: 28px 0; }
.stat, .card, .panel {
  background: var(--panel); border: 1px solid var(--line); border-radius: 16px;
}
.stat { padding: 22px; }
.stat b { display: block; font-family: "Cormorant Garamond", serif; font-size: 40px; color: var(--gold); }
.stat span { color: var(--muted); font-size: 12px; letter-spacing: .16em; text-transform: uppercase; }
.card { overflow: hidden; }
.card-h { padding: 20px 22px; border-bottom: 1px solid var(--line); }
.card-h p { color: var(--muted); font-size: 14px; margin-top: 4px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; min-width: 720px; }
th { text-align: left; font-size: 11px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--muted); font-weight: 500; background: var(--raised); padding: 12px 18px; }
td { padding: 14px 18px; border-top: 1px solid var(--line); font-size: 14px; vertical-align: middle; }
.gold { color: var(--gold); font-weight: 700; text-decoration: none; }
.muted { color: var(--muted); }
.tag { display: inline-block; background: var(--raised); color: var(--gold); padding: 4px 10px; border-radius: 6px; font-size: 13px; font-weight: 600; }
.grid3 { display: grid; gap: 12px; grid-template-columns: 1fr; margin: 22px 0; }
.panel { padding: 20px; }
.chip { display: flex; justify-content: space-between; gap: 12px; padding: 8px 0; font-size: 14px; border-bottom: 1px solid var(--line); }
.chip:last-child { border: 0; }
footer { border-top: 1px solid var(--line); padding: 22px 0; color: var(--muted); font-size: 14px; }
.foot { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.modal-bg { position: fixed; inset: 0; background: rgba(8,9,12,.82); display: none; place-items: center; padding: 16px; z-index: 50; }
.modal-bg.open { display: grid; }
.modal { width: min(440px, 100%); background: var(--panel); border: 1px solid var(--line); border-radius: 16px; padding: 24px; }
.tg { display: block; margin-top: 18px; padding: 18px; border: 1px solid rgba(212,175,55,.4); border-radius: 12px; text-decoration: none; background: var(--raised); }
.tg b { display: block; font-family: "Cormorant Garamond", serif; font-size: 28px; }
.tg span { color: var(--gold); }
@media (min-width: 800px) { .grid3 { grid-template-columns: 1fr 1fr 1fr; } }
@media (max-width: 700px) {
  form.row { flex-direction: column; }
  .btn { width: 100%; }
}
"""


def layout(title, body, active=""):
    def nav(href, key, label):
        cls = "active" if active == key else ""
        return f'<a class="{cls}" href="{href}">{label}</a>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="wrap nav">
    <a class="brand" href="/">
      <span class="mark">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M10 13a5 5 0 007.07 0l1.41-1.41a5 5 0 00-7.07-7.07L10 5.93" stroke="currentColor" stroke-width="1.8"/><path d="M14 11a5 5 0 00-7.07 0L5.52 12.41a5 5 0 007.07 7.07L14 18.07" stroke="currentColor" stroke-width="1.8"/></svg>
      </span>
      <span><b>SmartLink</b><small>Shuvo Ahmed</small></span>
    </a>
    <nav class="menu">
      {nav("/", "home", "Create")}
      {nav("/dashboard", "dashboard", "Dashboard")}
      {nav("/live-console", "live", "Live")}
      <button type="button" class="gold" onclick="openSupport()">Support</button>
    </nav>
  </div>
</header>
<main><div class="wrap">{body}</div></main>
<footer>
  <div class="wrap foot">
    <span>Shuvo Ahmed SmartLink</span>
    <button type="button" class="gold" style="background:none;border:0;cursor:pointer;font:inherit;color:var(--gold)" onclick="openSupport()">Support · Telegram</button>
  </div>
</footer>
<div class="modal-bg" id="supportModal" onclick="if(event.target===this)closeSupport()">
  <div class="modal">
    <p class="kicker">Support</p>
    <h2 style="font-size:32px;margin:8px 0 10px">Direct line</h2>
    <p class="muted">Tap the name to open Telegram and message Shuvo Ahmed.</p>
    <a class="tg" href="{SUPPORT_URL}" target="_blank" rel="noopener">
      <b>{SUPPORT_NAME}</b>
      <span>{SUPPORT_HANDLE}</span>
      <p class="muted" style="margin-top:10px;letter-spacing:.16em;text-transform:uppercase;font-size:11px">Open Telegram →</p>
    </a>
    <p style="margin-top:14px"><button type="button" onclick="closeSupport()" style="background:none;border:0;color:var(--muted);cursor:pointer">Close</button></p>
  </div>
</div>
<script>
function openSupport(){{ document.getElementById('supportModal').classList.add('open'); }}
function closeSupport(){{ document.getElementById('supportModal').classList.remove('open'); }}
</script>
</body>
</html>"""


@app.route("/")
def home():
    body = """
    <section class="hero">
      <p class="kicker">Private analytics</p>
      <h1>Short links with a full paper trail.</h1>
      <p>Every click records country, device, OS, browser, date and time — separately for each link you create.</p>
      <form class="row" method="POST" action="/create">
        <input type="url" name="url" placeholder="https://example.com/your-page" required>
        <button class="btn" type="submit">Create link</button>
      </form>
    </section>
    """
    return layout("Shuvo Ahmed SmartLink", body, "home")


@app.route("/create", methods=["POST"])
def create_link():
    original_url = (request.form.get("url") or "").strip()
    if not original_url.startswith(("http://", "https://")):
        return "Invalid URL", 400
    short_code = generate_short_code()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO links (short_code, original_url) VALUES (%s, %s)",
                (short_code, original_url),
            )
        conn.commit()
    short_url = request.host_url + short_code
    safe_url = html.escape(short_url)
    body = f"""
    <p class="kicker">Ready</p>
    <h1>Link created</h1>
    <div class="card" style="margin-top:24px;padding:24px">
      <p class="muted">Your SmartLink</p>
      <p style="margin:10px 0 18px"><a class="gold" href="{safe_url}">{safe_url}</a></p>
      <a class="btn" href="/dashboard">Open dashboard</a>
    </div>
    """
    return layout("Link created · SmartLink", body, "home")


@app.route("/dashboard")
def dashboard():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT short_code, original_url, clicks, created_at
                FROM links ORDER BY id DESC
            """)
            links = cur.fetchall()
            cur.execute("SELECT COUNT(*) FROM links")
            total_links = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(clicks), 0) FROM links")
            total_clicks = cur.fetchone()[0]

    rows = ""
    for short, url, clicks, created in links:
        safe_url = html.escape(url)
        display = safe_url if len(url) < 58 else html.escape(url[:55] + "...")
        rows += f"""
        <tr>
          <td><a class="gold" href="/{html.escape(short)}">/{html.escape(short)}</a></td>
          <td class="muted" title="{safe_url}">{display}</td>
          <td>{int(clicks)}</td>
          <td class="muted">{format_dt(created)}</td>
          <td><a href="/analytics/{html.escape(short)}">View A–Z</a></td>
        </tr>
        """
    if not rows:
        rows = '<tr><td colspan="5" class="muted" style="text-align:center;padding:48px">No links yet. Create one from the home page.</td></tr>'

    body = f"""
    <p class="kicker">Overview</p>
    <h1>Dashboard</h1>
    <div class="stats">
      <div class="stat"><b>{total_links}</b><span>Links created</span></div>
      <div class="stat"><b>{total_clicks}</b><span>Total clicks</span></div>
    </div>
    <div class="card">
      <div class="card-h">
        <h2>Every link, separately</h2>
        <p>Open any row to see country, device, browser, date and time for that link only.</p>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Short link</th><th>Destination</th><th>Clicks</th><th>Created</th><th>Details</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>
    """
    return layout("Dashboard · SmartLink", body, "dashboard")


@app.route("/analytics/<short_code>")
def analytics(short_code):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, short_code, original_url, clicks, created_at
                FROM links WHERE short_code = %s
            """, (short_code,))
            link = cur.fetchone()
            if not link:
                abort(404)
            link_id, sc, original_url, clicks, created_at = link
            cur.execute("""
                SELECT country, device, operating_system, browser, clicked_at
                FROM click_logs WHERE link_id = %s
                ORDER BY id DESC LIMIT 200
            """, (link_id,))
            click_rows = cur.fetchall()
            cur.execute("""
                SELECT country, COUNT(*) FROM click_logs
                WHERE link_id = %s GROUP BY country ORDER BY COUNT(*) DESC LIMIT 8
            """, (link_id,))
            top_countries = cur.fetchall()
            cur.execute("""
                SELECT device, COUNT(*) FROM click_logs
                WHERE link_id = %s GROUP BY device ORDER BY COUNT(*) DESC LIMIT 8
            """, (link_id,))
            top_devices = cur.fetchall()
            cur.execute("""
                SELECT browser, COUNT(*) FROM click_logs
                WHERE link_id = %s GROUP BY browser ORDER BY COUNT(*) DESC LIMIT 8
            """, (link_id,))
            top_browsers = cur.fetchall()

    def chips(items):
        if not items:
            return '<p class="muted">No data yet</p>'
        out = ""
        for name, n in items:
            out += f'<div class="chip"><span>{html.escape(str(name or "Unknown"))}</span><b class="gold">{int(n)}</b></div>'
        return out

    rows = ""
    for country, device, os_name, browser, clicked_at in click_rows:
        rows += f"""
        <tr>
          <td><span class="tag">{html.escape(country or "Unknown")}</span></td>
          <td>{html.escape(device or "Others")}</td>
          <td>{html.escape(os_name or "Others")}</td>
          <td>{html.escape(browser or "Others")}</td>
          <td class="muted">{format_dt(clicked_at)}</td>
        </tr>
        """
    if not rows:
        rows = '<tr><td colspan="5" class="muted" style="text-align:center;padding:48px">No clicks yet for this link.</td></tr>'

    body = f"""
    <p><a class="gold" href="/dashboard">← Dashboard</a></p>
    <h1 style="margin-top:12px">/{html.escape(sc)}</h1>
    <p class="muted" style="margin:8px 0 16px;word-break:break-all">{html.escape(original_url)}</p>
    <p style="font-family:'Cormorant Garamond',serif;font-size:48px;color:var(--gold)">{int(clicks)} <span class="muted" style="font-size:22px">clicks</span></p>
    <p class="muted">Created {format_dt(created_at)}</p>
    <div class="grid3">
      <div class="panel"><p class="kicker">Countries</p>{chips(top_countries)}</div>
      <div class="panel"><p class="kicker">Devices</p>{chips(top_devices)}</div>
      <div class="panel"><p class="kicker">Browsers</p>{chips(top_browsers)}</div>
    </div>
    <div class="card">
      <div class="card-h">
        <h2>Click log</h2>
        <p>Country · device · OS · browser · date · time</p>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Country</th><th>Device</th><th>OS</th><th>Browser</th><th>Date & time</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>
    """
    return layout(f"Analytics · /{sc}", body, "dashboard")


@app.route("/api/live-clicks")
def live_clicks():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, short_code, country, device, operating_system, browser, clicked_at
                FROM click_logs ORDER BY id DESC LIMIT 120
            """)
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
            "clicked_at": row[6].isoformat() if row[6] else None,
        })
    return jsonify(data)


@app.route("/live-console")
def live_console():
    body = """
    <p class="kicker">Live</p>
    <h1>Click console</h1>
    <p class="muted" style="margin:8px 0 22px">Country, device, OS, browser, date and time — updating every 2 seconds.</p>
    <div class="card">
      <input id="search" class="search" placeholder="Search country, device, browser or link…">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Date & time</th><th>Link</th><th>Country</th>
              <th>Device</th><th>OS</th><th>Browser</th>
            </tr>
          </thead>
          <tbody id="events">
            <tr><td colspan="6" class="muted" style="text-align:center;padding:48px">Waiting for clicks…</td></tr>
          </tbody>
        </table>
      </div>
    </div>
    <script>
    let events = [];
    function renderEvents() {
      const q = document.getElementById('search').value.toLowerCase();
      const body = document.getElementById('events');
      const filtered = events.filter(e => (
        e.short_code + ' ' + e.country + ' ' + e.device + ' ' + e.os + ' ' + e.browser
      ).toLowerCase().includes(q));
      if (!filtered.length) {
        body.innerHTML = "<tr><td colspan='6' class='muted' style='text-align:center;padding:48px'>No matching events</td></tr>";
        return;
      }
      body.innerHTML = filtered.map(e => {
        const t = e.clicked_at ? new Date(e.clicked_at).toLocaleString() : '—';
        return `<tr>
          <td class="muted">${t}</td>
          <td><a class="gold" href="/analytics/\( {e.short_code}">/ \){e.short_code}</a></td>
          <td><span class="tag">${e.country}</span></td>
          <td>${e.device}</td>
          <td>${e.os}</td>
          <td>${e.browser}</td>
        </tr>`;
      }).join('');
    }
    async function loadEvents() {
      try {
        const res = await fetch('/api/live-clicks', { cache: 'no-store' });
        if (!res.ok) return;
        events = await res.json();
        renderEvents();
      } catch (err) {}
    }
    document.getElementById('search').addEventListener('input', renderEvents);
    loadEvents();
    setInterval(loadEvents, 2000);
    </script>
    """
    return layout("Live Console · SmartLink", body, "live")


@app.route("/support")
def support():
    return redirect(SUPPORT_URL)


@app.route("/<short_code>")
def redirect_short_link(short_code):
    reserved = {"create", "dashboard", "analytics", "live-console", "health", "api", "support"}
    if short_code in reserved:
        abort(404)

    user_agent = request.headers.get("User-Agent", "")
    ip = get_client_ip()
    country = get_country(ip)
    device = get_device(user_agent)
    operating_system = get_operating_system(user_agent)
    browser = get_browser(user_agent)
    ip_hash_value = hash_ip(ip)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, original_url FROM links WHERE short_code = %s",
                (short_code,),
            )
            link = cur.fetchone()
            if not link:
                abort(404)
            link_id, original_url = link
            cur.execute("UPDATE links SET clicks = clicks + 1 WHERE id = %s", (link_id,))
            cur.execute("""
                INSERT INTO click_logs
                (link_id, short_code, country, device, operating_system, browser, ip_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                link_id, short_code, country, device,
                operating_system, browser, ip_hash_value,
            ))
        conn.commit()
    return redirect(original_url)


@app.route("/health")
def health():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()[0]
        return jsonify({"status": "ok", "database": result == 1})
    except Exception as error:
        return jsonify({"status": "error", "database": False, "error": str(error)}), 500


try:
    setup_database()
except Exception as exc:
    print("database setup:", exc)

if __name__ == "__main__":
    print("SHUVO AHMED SMARTLINK · PREMIUM")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)