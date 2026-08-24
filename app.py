import os
import random
import string
import hashlib
import urllib.request
import json
from datetime import datetime

import psycopg
from dotenv import load_dotenv
from flask import Flask, request, redirect, jsonify, abort

load_dotenv()

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not found in .env")


# ============================================================
# DATABASE
# ============================================================

def get_db():
    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=10
    )


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
                    link_id BIGINT REFERENCES links(id)
                        ON DELETE CASCADE,
                    short_code TEXT NOT NULL,
                    country TEXT DEFAULT 'Unknown',
                    device TEXT DEFAULT 'Unknown',
                    operating_system TEXT DEFAULT 'Unknown',
                    browser TEXT DEFAULT 'Unknown',
                    ip_hash TEXT,
                    clicked_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

        conn.commit()


# ============================================================
# SHORT CODE
# ============================================================

def generate_short_code(length=7):
    chars = string.ascii_letters + string.digits

    while True:
        code = "".join(
            random.choice(chars)
            for _ in range(length)
        )

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM links WHERE short_code = %s",
                    (code,)
                )
                exists = cur.fetchone()

        if not exists:
            return code


# ============================================================
# VISITOR INFORMATION
# ============================================================

def get_client_ip():
    # Render + most proxies
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    return request.remote_addr or ""


def get_country(ip):
    if not ip or ip in ("127.0.0.1", "::1"):
        return "Local"

    try:
        url = f"https://ipwho.is/{ip}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ShuvoAhmedSmartLink/2.0"}
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))

        if data.get("success"):
            country = data.get("country")
            if country:
                return country
    except Exception:
        pass

    return "Unknown"


def get_device(user_agent):
    ua = (user_agent or "").lower()
    if "ipad" in ua: return "iPad"
    if "iphone" in ua: return "iPhone"
    if "android" in ua: return "Android"
    if "windows" in ua: return "Windows"
    if "macintosh" in ua or "mac os" in ua: return "Mac"
    if "linux" in ua: return "Linux"
    if "cros" in ua: return "ChromeOS"
    return "Unknown"


def get_operating_system(user_agent):
    ua = (user_agent or "").lower()
    if "iphone" in ua or "ipad" in ua: return "iOS"
    if "android" in ua: return "Android"
    if "windows" in ua: return "Windows"
    if "mac os" in ua or "macintosh" in ua: return "macOS"
    if "cros" in ua: return "ChromeOS"
    if "linux" in ua: return "Linux"
    return "Unknown"


def get_browser(user_agent):
    ua = (user_agent or "").lower()
    if "edg/" in ua: return "Edge"
    if "opr/" in ua or "opera" in ua: return "Opera"
    if "firefox/" in ua: return "Firefox"
    if "samsungbrowser/" in ua: return "Samsung"
    if "chrome/" in ua: return "Chrome"
    if "safari/" in ua and "chrome" not in ua: return "Safari"
    return "Unknown"


def hash_ip(ip):
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()


def format_dt(dt):
    if not dt:
        return "—"
    try:
        return dt.strftime("%d %b %Y • %I:%M %p")
    except:
        return str(dt)


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Shuvo Ahmed SmartLink</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {
    --primary: #4f46e5;
    --primary-dark: #4338ca;
    --bg: #f8fafc;
    --card: #ffffff;
    --text: #0f172a;
    --muted: #64748b;
    --border: #e2e8f0;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Inter', system-ui, sans-serif;
    background: linear-gradient(135deg, #f0f4ff 0%, #f8fafc 50%, #eef2ff 100%);
    min-height: 100vh;
    color: var(--text);
}
.container { max-width: 720px; margin: 0 auto; padding: 40px 20px; }
.card {
    background: var(--card);
    border-radius: 24px;
    padding: 40px 36px;
    box-shadow: 0 20px 50px -12px rgba(79, 70, 229, 0.12);
    border: 1px solid rgba(255,255,255,0.8);
}
.logo {
    font-size: 28px;
    font-weight: 800;
    letter-spacing: -0.5px;
    margin-bottom: 8px;
    background: linear-gradient(90deg, #4f46e5, #7c3aed);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.subtitle { color: var(--muted); font-size: 15px; margin-bottom: 32px; }
form { display: flex; gap: 12px; margin-bottom: 28px; }
input[type="url"] {
    flex: 1;
    padding: 16px 18px;
    border: 2px solid var(--border);
    border-radius: 14px;
    font-size: 15px;
    font-family: inherit;
    transition: all 0.2s;
    outline: none;
}
input[type="url"]:focus {
    border-color: var(--primary);
    box-shadow: 0 0 0 4px rgba(79, 70, 229, 0.12);
}
button {
    padding: 16px 28px;
    background: linear-gradient(135deg, #4f46e5, #6366f1);
    color: white;
    border: none;
    border-radius: 14px;
    font-weight: 700;
    font-size: 15px;
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
}
button:hover {
    transform: translateY(-1px);
    box-shadow: 0 8px 20px rgba(79, 70, 229, 0.35);
}
.menu {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}
.menu a {
    padding: 12px 18px;
    background: #eef2ff;
    color: #4338ca;
    text-decoration: none;
    border-radius: 12px;
    font-weight: 600;
    font-size: 14px;
    transition: all 0.2s;
}
.menu a:hover {
    background: #e0e7ff;
    transform: translateY(-1px);
}
@media (max-width: 600px) {
    form { flex-direction: column; }
    button { width: 100%; }
    .card { padding: 28px 22px; }
}
</style>
</head>
<body>
<div class="container">
    <div class="card">
        <div class="logo">🔗 Shuvo Ahmed SmartLink</div>
        <p class="subtitle">Create powerful short links with real-time analytics</p>
        
        <form method="POST" action="/create">
            <input type="url" name="url" placeholder="https://example.com/your-long-url" required>
            <button type="submit">Create Link</button>
        </form>

        <div class="menu">
            <a href="/dashboard">📊 Dashboard</a>
            <a href="/live-console">🔴 Live Console</a>
            <a href="/health">❤️ Health</a>
        </div>
    </div>
</div>
</body>
</html>
"""


# ============================================================
# CREATE SHORT LINK
# ============================================================

@app.route("/create", methods=["POST"])
def create_link():
    original_url = request.form.get("url", "").strip()

    if not original_url.startswith(("http://", "https://")):
        return "Invalid URL", 400

    short_code = generate_short_code()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO links (short_code, original_url) VALUES (%s, %s)",
                (short_code, original_url)
            )
        conn.commit()

    short_url = request.host_url + short_code

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Link Created</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
body {{
    font-family: 'Inter', sans-serif;
    background: linear-gradient(135deg, #f0f4ff, #eef2ff);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
}}
.card {{
    background: white;
    border-radius: 24px;
    padding: 48px 40px;
    text-align: center;
    box-shadow: 0 25px 50px -12px rgba(79,70,229,0.15);
    max-width: 520px;
    width: 100%;
}}
h1 {{ font-size: 26px; font-weight: 800; margin-bottom: 12px; color: #0f172a; }}
.success {{ color: #16a34a; font-size: 15px; margin-bottom: 28px; }}
.link-box {{
    background: #f8fafc;
    border: 2px solid #e2e8f0;
    border-radius: 14px;
    padding: 18px;
    margin-bottom: 28px;
    word-break: break-all;
}}
.link-box a {{
    color: #4f46e5;
    font-weight: 700;
    font-size: 18px;
    text-decoration: none;
}}
.btn {{
    display: inline-block;
    padding: 14px 28px;
    background: linear-gradient(135deg, #4f46e5, #6366f1);
    color: white;
    text-decoration: none;
    border-radius: 12px;
    font-weight: 700;
    transition: all 0.2s;
}}
.btn:hover {{ transform: translateY(-2px); box-shadow: 0 10px 20px rgba(79,70,229,0.3); }}
</style>
</head>
<body>
<div class="card">
    <h1>✅ Link Created!</h1>
    <p class="success">Your SmartLink is ready to use</p>
    <div class="link-box">
        <a href="{short_url}" target="_blank">{short_url}</a>
    </div>
    <a href="/dashboard" class="btn">📊 Open Dashboard</a>
</div>
</body>
</html>
"""


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT short_code, original_url, clicks, created_at
                FROM links
                ORDER BY id DESC
            """)
            links = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM links")
            total_links = cur.fetchone()[0]

            cur.execute("SELECT COALESCE(SUM(clicks), 0) FROM links")
            total_clicks = cur.fetchone()[0]

    rows = ""
    for link in links:
        short, url, clicks, created = link
        display_url = url if len(url) < 55 else url[:52] + "..."
        rows += f"""
        <tr>
            <td>
                <a href="/{short}" class="short-link">/{short}</a>
            </td>
            <td class="url-cell" title="{url}">{display_url}</td>
            <td><span class="badge clicks">{clicks}</span></td>
            <td class="date">{format_dt(created)}</td>
            <td>
                <a href="/analytics/{short}" class="analytics-btn">View Details →</a>
            </td>
        </tr>
        """

    if not rows:
        rows = """
        <tr>
            <td colspan="5" style="text-align:center; padding:40px; color:#64748b;">
                No links created yet. Create your first SmartLink!
            </td>
        </tr>
        """

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard • SmartLink</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {{
    --primary: #4f46e5;
    --bg: #f1f5f9;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    font-family: 'Inter', system-ui, sans-serif;
    background: var(--bg);
    color: #0f172a;
    min-height: 100vh;
}}
.container {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px; }}
.header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 32px;
    flex-wrap: wrap;
    gap: 16px;
}}
.header h1 {{
    font-size: 28px;
    font-weight: 800;
    letter-spacing: -0.5px;
}}
.header a {{
    color: #4f46e5;
    text-decoration: none;
    font-weight: 600;
    font-size: 14px;
}}
.stats {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 28px;
}}
.stat-card {{
    background: white;
    border-radius: 18px;
    padding: 24px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.04);
    border: 1px solid #e2e8f0;
}}
.stat-card h2 {{
    font-size: 32px;
    font-weight: 800;
    color: #4f46e5;
    margin-bottom: 4px;
}}
.stat-card p {{
    color: #64748b;
    font-size: 14px;
    font-weight: 500;
}}
.card {{
    background: white;
    border-radius: 20px;
    padding: 8px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.05);
    border: 1px solid #e2e8f0;
    overflow: hidden;
}}
.card-header {{
    padding: 20px 24px 12px;
    font-size: 17px;
    font-weight: 700;
}}
table {{
    width: 100%;
    border-collapse: collapse;
}}
th {{
    text-align: left;
    padding: 14px 20px;
    font-size: 12px;
    font-weight: 600;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    background: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
}}
td {{
    padding: 16px 20px;
    border-bottom: 1px solid #f1f5f9;
    font-size: 14px;
    vertical-align: middle;
}}
tr:last-child td {{ border-bottom: none; }}
tr:hover td {{ background: #f8fafc; }}
.short-link {{
    color: #4f46e5;
    font-weight: 700;
    text-decoration: none;
    font-size: 15px;
}}
.short-link:hover {{ text-decoration: underline; }}
.url-cell {{
    color: #475569;
    max-width: 280px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.badge {{
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-weight: 700;
    font-size: 13px;
}}
.badge.clicks {{
    background: #eef2ff;
    color: #4338ca;
}}
.date {{
    color: #64748b;
    font-size: 13px;
    white-space: nowrap;
}}
.analytics-btn {{
    color: #4f46e5;
    font-weight: 600;
    text-decoration: none;
    font-size: 13px;
}}
.analytics-btn:hover {{ text-decoration: underline; }}
.footer-links {{
    margin-top: 24px;
    display: flex;
    gap: 16px;
}}
.footer-links a {{
    color: #4f46e5;
    font-weight: 600;
    text-decoration: none;
    font-size: 14px;
}}
@media (max-width: 700px) {{
    .url-cell {{ max-width: 140px; }}
    th, td {{ padding: 12px 14px; }}
}}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📊 Dashboard</h1>
        <a href="/">← Create New Link</a>
    </div>

    <div class="stats">
        <div class="stat-card">
            <h2>{total_links}</h2>
            <p>Total Links</p>
        </div>
        <div class="stat-card">
            <h2>{total_clicks}</h2>
            <p>Total Clicks</p>
        </div>
    </div>

    <div class="card">
        <div class="card-header">All Your SmartLinks</div>
        <div style="overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Short Link</th>
                        <th>Destination</th>
                        <th>Clicks</th>
                        <th>Created</th>
                        <th>Analytics</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
    </div>

    <div class="footer-links">
        <a href="/live-console">🔴 Live Console</a>
        <a href="/">+ Create New</a>
    </div>
</div>
</body>
</html>
"""


# ============================================================
# ANALYTICS
# ============================================================

@app.route("/analytics/<short_code>")
def analytics(short_code):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, short_code, original_url, clicks, created_at
                FROM links
                WHERE short_code = %s
            """, (short_code,))
            link = cur.fetchone()

            if not link:
                abort(404)

            link_id, sc, original_url, clicks, created_at = link

            cur.execute("""
                SELECT country, device, operating_system, browser, clicked_at
                FROM click_logs
                WHERE link_id = %s
                ORDER BY id DESC
                LIMIT 150
            """, (link_id,))
            click_rows = cur.fetchall()

            # Simple aggregates
            cur.execute("""
                SELECT country, COUNT(*) 
                FROM click_logs 
                WHERE link_id = %s 
                GROUP BY country 
                ORDER BY COUNT(*) DESC 
                LIMIT 5
            """, (link_id,))
            top_countries = cur.fetchall()

            cur.execute("""
                SELECT device, COUNT(*) 
                FROM click_logs 
                WHERE link_id = %s 
                GROUP BY device 
                ORDER BY COUNT(*) DESC 
                LIMIT 5
            """, (link_id,))
            top_devices = cur.fetchall()

    # Build top countries / devices html
    countries_html = ""
    for c, cnt in top_countries:
        countries_html += f'<div class="chip"><span>{c or "Unknown"}</span><strong>{cnt}</strong></div>'

    devices_html = ""
    for d, cnt in top_devices:
        devices_html += f'<div class="chip"><span>{d or "Unknown"}</span><strong>{cnt}</strong></div>'

    if not countries_html:
        countries_html = '<div class="empty">No data yet</div>'
    if not devices_html:
        devices_html = '<div class="empty">No data yet</div>'

    rows = ""
    for click in click_rows:
        country, device, os, browser, clicked_at = click
        rows += f"""
        <tr>
            <td><span class="tag">{country or "Unknown"}</span></td>
            <td>{device or "Unknown"}</td>
            <td>{os or "Unknown"}</td>
            <td>{browser or "Unknown"}</td>
            <td class="time">{format_dt(clicked_at)}</td>
        </tr>
        """

    if not rows:
        rows = """
        <tr>
            <td colspan="5" style="text-align:center;padding:40px;color:#64748b;">
                No clicks recorded yet for this link.
            </td>
        </tr>
        """

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Analytics • /{sc}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    font-family: 'Inter', system-ui, sans-serif;
    background: #f1f5f9;
    color: #0f172a;
    min-height: 100vh;
}}
.container {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px; }}
.back {{
    display: inline-block;
    margin-bottom: 20px;
    color: #4f46e5;
    text-decoration: none;
    font-weight: 600;
    font-size: 14px;
}}
.header-card {{
    background: white;
    border-radius: 20px;
    padding: 28px 32px;
    margin-bottom: 24px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.04);
    border: 1px solid #e2e8f0;
}}
.header-card h1 {{
    font-size: 24px;
    font-weight: 800;
    margin-bottom: 8px;
}}
.header-card .url {{
    color: #64748b;
    font-size: 14px;
    word-break: break-all;
    margin-bottom: 16px;
}}
.big-stat {{
    font-size: 42px;
    font-weight: 800;
    color: #4f46e5;
}}
.big-stat span {{
    font-size: 16px;
    font-weight: 600;
    color: #64748b;
    margin-left: 8px;
}}
.grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 24px;
}}
@media (max-width: 700px) {{ .grid {{ grid-template-columns: 1fr; }} }}
.panel {{
    background: white;
    border-radius: 18px;
    padding: 22px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.04);
    border: 1px solid #e2e8f0;
}}
.panel h3 {{
    font-size: 14px;
    font-weight: 700;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    margin-bottom: 16px;
}}
.chip {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 14px;
    background: #f8fafc;
    border-radius: 10px;
    margin-bottom: 8px;
    font-size: 14px;
}}
.chip strong {{
    background: #eef2ff;
    color: #4338ca;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 13px;
}}
.empty {{ color: #94a3b8; font-size: 14px; }}
.card {{
    background: white;
    border-radius: 20px;
    overflow: hidden;
    box-shadow: 0 4px 20px rgba(0,0,0,0.04);
    border: 1px solid #e2e8f0;
}}
.card-title {{
    padding: 20px 24px;
    font-size: 16px;
    font-weight: 700;
    border-bottom: 1px solid #f1f5f9;
}}
table {{ width: 100%; border-collapse: collapse; }}
th {{
    text-align: left;
    padding: 13px 20px;
    font-size: 12px;
    font-weight: 600;
    color: #64748b;
    text-transform: uppercase;
    background: #f8fafc;
}}
td {{
    padding: 14px 20px;
    border-bottom: 1px solid #f1f5f9;
    font-size: 14px;
}}
tr:last-child td {{ border-bottom: none; }}
.tag {{
    display: inline-block;
    padding: 4px 10px;
    background: #ecfdf5;
    color: #047857;
    border-radius: 6px;
    font-weight: 600;
    font-size: 13px;
}}
.time {{ color: #64748b; font-size: 13px; white-space: nowrap; }}
</style>
</head>
<body>
<div class="container">
    <a href="/dashboard" class="back">← Back to Dashboard</a>

    <div class="header-card">
        <h1>/{sc}</h1>
        <div class="url">{original_url}</div>
        <div class="big-stat">{clicks} <span>total clicks</span></div>
        <div style="margin-top:8px;color:#64748b;font-size:13px;">
            Created: {format_dt(created_at)}
        </div>
    </div>

    <div class="grid">
        <div class="panel">
            <h3>Top Countries</h3>
            {countries_html}
        </div>
        <div class="panel">
            <h3>Top Devices</h3>
            {devices_html}
        </div>
    </div>

    <div class="card">
        <div class="card-title">Recent Clicks (Latest 150)</div>
        <div style="overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Country</th>
                        <th>Device</th>
                        <th>OS</th>
                        <th>Browser</th>
                        <th>Date & Time</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
    </div>
</div>
</body>
</html>
"""


# ============================================================
# LIVE CLICK API
# ============================================================

@app.route("/api/live-clicks")
def live_clicks():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, short_code, country, device, operating_system, browser, clicked_at
                FROM click_logs
                ORDER BY id DESC
                LIMIT 100
            """)
            rows = cur.fetchall()

    data = []
    for row in rows:
        data.append({
            "id": row[0],
            "short_code": row[1],
            "country": row[2] or "Unknown",
            "device": row[3] or "Unknown",
            "os": row[4] or "Unknown",
            "browser": row[5] or "Unknown",
            "clicked_at": row[6].isoformat() if row[6] else None
        })

    return jsonify(data)


# ============================================================
# LIVE CONSOLE
# ============================================================

@app.route("/live-console")
def live_console():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Live Console • SmartLink</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body {
    font-family: 'Inter', system-ui, sans-serif;
    background: #0b1120;
    color: #e2e8f0;
    min-height: 100vh;
}
.container { max-width: 1200px; margin: 0 auto; padding: 28px 20px; }
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 28px;
    flex-wrap: wrap;
    gap: 16px;
}
.header h1 {
    font-size: 26px;
    font-weight: 800;
    letter-spacing: -0.5px;
}
.header p { color: #94a3b8; font-size: 14px; margin-top: 4px; }
.live-badge {
    background: linear-gradient(90deg, #064e3b, #065f46);
    color: #6ee7b7;
    padding: 8px 16px;
    border-radius: 30px;
    font-weight: 700;
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.dot {
    width: 8px;
    height: 8px;
    background: #34d399;
    border-radius: 50%;
    animation: pulse 1.5s infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}
.panel {
    background: #111827;
    border-radius: 18px;
    overflow: hidden;
    border: 1px solid #1e293b;
}
.search {
    width: 100%;
    padding: 16px 20px;
    background: #0f172a;
    border: none;
    border-bottom: 1px solid #1e293b;
    color: white;
    font-size: 15px;
    font-family: inherit;
    outline: none;
}
.search::placeholder { color: #64748b; }
.table-wrapper { overflow-x: auto; }
table { width: 100%; min-width: 800px; border-collapse: collapse; }
th {
    text-align: left;
    padding: 14px 18px;
    font-size: 11px;
    font-weight: 600;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    background: #0f172a;
}
td {
    padding: 14px 18px;
    border-bottom: 1px solid #1e293b;
    font-size: 14px;
}
tr:hover td { background: #1e293b; }
.country-tag {
    background: #064e3b;
    color: #6ee7b7;
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
}
.back {
    display: inline-block;
    margin-top: 24px;
    color: #818cf8;
    text-decoration: none;
    font-weight: 600;
    font-size: 14px;
}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div>
            <h1>🔴 Live Console</h1>
            <p>Real-time click activity across all links</p>
        </div>
        <div class="live-badge">
            <div class="dot"></div>
            LIVE
        </div>
    </div>

    <div class="panel">
        <input id="search" class="search" placeholder="Search by country, device, browser or short link...">
        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Link</th>
                        <th>Country</th>
                        <th>Device</th>
                        <th>OS</th>
                        <th>Browser</th>
                    </tr>
                </thead>
                <tbody id="events">
                    <tr>
                        <td colspan="6" style="text-align:center;padding:40px;color:#64748b;">
                            Waiting for clicks...
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <a href="/dashboard" class="back">← Back to Dashboard</a>
</div>

<script>
let events = [];

function renderEvents() {
    const search = document.getElementById("search").value.toLowerCase();
    const body = document.getElementById("events");

    const filtered = events.filter(e => {
        const text = (e.short_code + " " + e.country + " " + e.device + " " + e.os + " " + e.browser).toLowerCase();
        return text.includes(search);
    });

    if (filtered.length === 0) {
        body.innerHTML = "<tr><td colspan='6' style='text-align:center;padding:40px;color:#64748b;'>No matching events</td></tr>";
        return;
    }

    body.innerHTML = filtered.map(e => {
        const time = new Date(e.clicked_at).toLocaleString();
        return `
        <tr>
            <td style="color:#94a3b8;font-size:13px;">${time}</td>
            <td style="font-weight:600;color:#a5b4fc;">/${e.short_code}</td>
            <td><span class="country-tag">${e.country}</span></td>
            <td>${e.device}</td>
            <td>${e.os}</td>
            <td>${e.browser}</td>
        </tr>`;
    }).join("");
}

async function loadEvents() {
    try {
        const res = await fetch("/api/live-clicks", { cache: "no-store" });
        if (!res.ok) return;
        events = await res.json();
        renderEvents();
    } catch (err) {
        console.log("Live console error:", err);
    }
}

document.getElementById("search").addEventListener("input", renderEvents);
loadEvents();
setInterval(loadEvents, 2000);
</script>
</body>
</html>
"""


# ============================================================
# SHORT LINK REDIRECT + CLICK TRACKING
# ============================================================

@app.route("/<short_code>")
def redirect_short_link(short_code):
    user_agent = request.headers.get("User-Agent", "")
    ip = get_client_ip()
    country = get_country(ip)
    device = get_device(user_agent)
    operating_system = get_operating_system(user_agent)
    browser = get_browser(user_agent)
    ip_hash = hash_ip(ip)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, original_url FROM links WHERE short_code = %s",
                (short_code,)
            )
            link = cur.fetchone()

            if not link:
                abort(404)

            link_id, original_url = link

            cur.execute(
                "UPDATE links SET clicks = clicks + 1 WHERE id = %s",
                (link_id,)
            )

            cur.execute("""
                INSERT INTO click_logs
                (link_id, short_code, country, device, operating_system, browser, ip_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                link_id, short_code, country, device,
                operating_system, browser, ip_hash
            ))

        conn.commit()

    return redirect(original_url)


# ============================================================
# HEALTH CHECK
# ============================================================

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
    except Exception as error:
        return jsonify({
            "status": "error",
            "database": False,
            "error": str(error)
        }), 500


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    setup_database()

    print()
    print("=" * 60)
    print("       SHUVO AHMED SMARTLINK  •  PREMIUM")
    print("=" * 60)
    print("Database       : CONNECTED")
    print("Link System    : ACTIVE")
    print("Click Tracking : ACTIVE")
    print("Analytics      : ACTIVE")
    print("Live Console   : ACTIVE")
    print("=" * 60)
    print("Home          : http://127.0.0.1:8080/")
    print("Dashboard     : http://127.0.0.1:8080/dashboard")
    print("Live Console  : http://127.0.0.1:8080/live-console")
    print("Health        : http://127.0.0.1:8080/health")
    print("=" * 60)
    print()

    app.run(host="127.0.0.1", port=8080, debug=True)