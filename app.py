import os
import random
import string
import hashlib
import urllib.request
import json

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
    forwarded = request.headers.get("X-Forwarded-For")

    if forwarded:
        return forwarded.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")

    if real_ip:
        return real_ip

    return request.remote_addr or ""


def get_country(ip):
    if not ip:
        return "Unknown"

    if ip in ("127.0.0.1", "::1"):
        return "Local / PC"

    try:
        url = "https://ipwho.is/" + ip

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ShuvoAhmedSmartLink/1.0"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=5
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

        if data.get("success"):
            return data.get(
                "country",
                "Unknown"
            )

    except Exception:
        pass

    return "Unknown"


def get_device(user_agent):
    ua = user_agent.lower()

    if "ipad" in ua:
        return "iPad"

    if "iphone" in ua:
        return "iPhone"

    if "android" in ua:
        return "Android"

    if "windows" in ua:
        return "Windows PC"

    if "macintosh" in ua:
        return "Mac"

    if "linux" in ua:
        return "Linux"

    if "cros" in ua:
        return "ChromeOS"

    return "Unknown"


def get_operating_system(user_agent):
    ua = user_agent.lower()

    if "iphone" in ua or "ipad" in ua:
        return "iOS / iPadOS"

    if "android" in ua:
        return "Android"

    if "windows" in ua:
        return "Windows"

    if "mac os x" in ua or "macintosh" in ua:
        return "macOS"

    if "cros" in ua:
        return "ChromeOS"

    if "linux" in ua:
        return "Linux"

    return "Unknown"


def get_browser(user_agent):
    ua = user_agent.lower()

    if "edg/" in ua:
        return "Microsoft Edge"

    if "opr/" in ua or "opera" in ua:
        return "Opera"

    if "firefox/" in ua:
        return "Firefox"

    if "samsungbrowser/" in ua:
        return "Samsung Internet"

    if "chrome/" in ua:
        return "Google Chrome"

    if "safari/" in ua:
        return "Safari"

    return "Unknown"


def hash_ip(ip):
    return hashlib.sha256(
        ip.encode("utf-8")
    ).hexdigest()


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    return """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shuvo Ahmed SmartLink</title>

<style>
body {
    margin: 0;
    padding: 30px;
    background: #f4f7fb;
    font-family: Arial, sans-serif;
}

.container {
    max-width: 900px;
    margin: auto;
}

.card {
    background: white;
    padding: 30px;
    border-radius: 18px;
    box-shadow: 0 10px 30px rgba(0,0,0,.08);
}

input {
    width: 70%;
    box-sizing: border-box;
    padding: 14px;
    border: 1px solid #ddd;
    border-radius: 10px;
}

button {
    padding: 14px 20px;
    border: 0;
    border-radius: 10px;
    background: #2563eb;
    color: white;
    font-weight: bold;
    cursor: pointer;
}

.menu {
    margin-top: 25px;
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

.menu a {
    padding: 12px 16px;
    background: #eef2ff;
    border-radius: 10px;
    color: #2563eb;
    text-decoration: none;
    font-weight: bold;
}

@media (max-width: 650px) {
    input {
        width: 100%;
        margin-bottom: 10px;
    }

    button {
        width: 100%;
    }
}
</style>
</head>

<body>

<div class="container">

<div class="card">

<h1>🔗 Shuvo Ahmed SmartLink</h1>

<p>Create and track your Smart Links.</p>

<form method="POST" action="/create">

<input
    type="url"
    name="url"
    placeholder="https://example.com"
    required
>

<button type="submit">
Create Link
</button>

</form>

<div class="menu">

<a href="/dashboard">
📊 Dashboard
</a>

<a href="/live-console">
🔴 Live Console
</a>

<a href="/health">
❤️ Health
</a>

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

    original_url = request.form.get(
        "url",
        ""
    ).strip()

    if not original_url.startswith(
        ("http://", "https://")
    ):
        return "Invalid URL", 400

    short_code = generate_short_code()

    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO links
                (short_code, original_url)
                VALUES (%s, %s)
                """,
                (
                    short_code,
                    original_url
                )
            )

        conn.commit()

    short_url = request.host_url + short_code

    return f"""
<!DOCTYPE html>
<html>
<head>
<title>Link Created</title>
</head>

<body style="font-family:Arial;padding:30px">

<h1>✅ Link Created Successfully</h1>

<p>Your SmartLink:</p>

<p>
<a href="{short_url}">
{short_url}
</a>
</p>

<p>
<a href="/dashboard">
📊 Open Dashboard
</a>
</p>

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
                SELECT
                    short_code,
                    original_url,
                    clicks,
                    created_at
                FROM links
                ORDER BY id DESC
            """)

            links = cur.fetchall()

            cur.execute(
                "SELECT COUNT(*) FROM links"
            )

            total_links = cur.fetchone()[0]

            cur.execute(
                "SELECT COALESCE(SUM(clicks), 0) FROM links"
            )

            total_clicks = cur.fetchone()[0]

    rows = ""

    for link in links:

        rows += f"""
        <tr>
            <td>
                <a href="/{link[0]}">
                    /{link[0]}
                </a>
            </td>

            <td>{link[1]}</td>

            <td>{link[2]}</td>

            <td>
                <a href="/analytics/{link[0]}">
                    Analytics
                </a>
            </td>
        </tr>
        """

    if not rows:
        rows = """
        <tr>
            <td colspan="4">
                No links created yet.
            </td>
        </tr>
        """

    return f"""
<!DOCTYPE html>
<html>

<head>

<meta name="viewport" content="width=device-width, initial-scale=1">

<title>SmartLink Dashboard</title>

<style>

body {{
    margin: 0;
    padding: 25px;
    background: #f4f7fb;
    font-family: Arial, sans-serif;
}}

.container {{
    max-width: 1150px;
    margin: auto;
}}

.stats {{
    display: flex;
    gap: 15px;
    flex-wrap: wrap;
}}

.stat {{
    flex: 1;
    min-width: 180px;
    background: white;
    padding: 22px;
    border-radius: 16px;
    box-shadow: 0 5px 20px rgba(0,0,0,.06);
}}

.card {{
    margin-top: 20px;
    background: white;
    padding: 22px;
    border-radius: 16px;
    overflow-x: auto;
}}

table {{
    width: 100%;
    border-collapse: collapse;
}}

th, td {{
    padding: 14px;
    border-bottom: 1px solid #ddd;
    text-align: left;
}}

a {{
    color: #2563eb;
    text-decoration: none;
    font-weight: bold;
}}

</style>

</head>

<body>

<div class="container">

<h1>📊 SmartLink Dashboard</h1>

<div class="stats">

<div class="stat">
<h2>{total_links}</h2>
<p>Total Links</p>
</div>

<div class="stat">
<h2>{total_clicks}</h2>
<p>Total Clicks</p>
</div>

</div>

<div class="card">

<h2>🔗 Links</h2>

<table>

<tr>
<th>Short Link</th>
<th>Destination</th>
<th>Clicks</th>
<th>Analytics</th>
</tr>

{rows}

</table>

</div>

<p>
<a href="/live-console">
🔴 Open Live Console
</a>
</p>

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

            cur.execute(
                """
                SELECT
                    id,
                    short_code,
                    original_url,
                    clicks
                FROM links
                WHERE short_code = %s
                """,
                (short_code,)
            )

            link = cur.fetchone()

            if not link:
                abort(404)

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
                LIMIT 100
                """,
                (link[0],)
            )

            click_rows = cur.fetchall()

    rows = ""

    for click in click_rows:

        rows += f"""
        <tr>
            <td>{click[0]}</td>
            <td>{click[1]}</td>
            <td>{click[2]}</td>
            <td>{click[3]}</td>
            <td>{click[4]}</td>
        </tr>
        """

    if not rows:
        rows = """
        <tr>
            <td colspan="5">
                No clicks yet.
            </td>
        </tr>
        """

    return f"""
<!DOCTYPE html>
<html>

<head>

<meta name="viewport" content="width=device-width, initial-scale=1">

<title>Link Analytics</title>

<style>

body {{
    margin: 0;
    padding: 25px;
    background: #f4f7fb;
    font-family: Arial, sans-serif;
}}

.container {{
    max-width: 1150px;
    margin: auto;
}}

.card {{
    background: white;
    padding: 25px;
    border-radius: 16px;
    overflow-x: auto;
}}

table {{
    width: 100%;
    border-collapse: collapse;
}}

th, td {{
    padding: 13px;
    border-bottom: 1px solid #ddd;
    text-align: left;
}}

</style>

</head>

<body>

<div class="container">

<h1>📈 Link Analytics</h1>

<div class="card">

<h2>/{link[1]}</h2>

<p>
Destination: {link[2]}
</p>

<p>
Total Clicks:
<strong>{link[3]}</strong>
</p>

<table>

<tr>
<th>Country</th>
<th>Device</th>
<th>OS</th>
<th>Browser</th>
<th>Time</th>
</tr>

{rows}

</table>

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
            "clicked_at": row[6].isoformat()
        })

    return jsonify(data)


# ============================================================
# LIVE CONSOLE
# ============================================================

@app.route("/live-console")
def live_console():

    return """
<!DOCTYPE html>
<html>

<head>

<meta name="viewport" content="width=device-width, initial-scale=1">

<title>SmartLink Live Console</title>

<style>

body {
    margin: 0;
    padding: 25px;
    background: #0f172a;
    color: white;
    font-family: Arial, sans-serif;
}

.container {
    max-width: 1250px;
    margin: auto;
}

.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 15px;
}

.live {
    background: #064e3b;
    color: #a7f3d0;
    padding: 9px 15px;
    border-radius: 20px;
    font-weight: bold;
}

.panel {
    margin-top: 25px;
    background: #111827;
    border-radius: 16px;
    overflow: hidden;
}

.search {
    width: 100%;
    box-sizing: border-box;
    padding: 15px;
    background: #0f172a;
    color: white;
    border: 0;
    border-bottom: 1px solid #334155;
    outline: none;
}

.table-wrapper {
    overflow-x: auto;
}

table {
    width: 100%;
    min-width: 850px;
    border-collapse: collapse;
}

th {
    background: #1e293b;
    color: #94a3b8;
}

th, td {
    padding: 14px;
    text-align: left;
    border-bottom: 1px solid #1e293b;
}

</style>

</head>

<body>

<div class="container">

<div class="header">

<div>
<h1>🔴 Live Console</h1>
<p>Real-time SmartLink click activity</p>
</div>

<div class="live">
● LIVE
</div>

</div>

<div class="panel">

<input
    id="search"
    class="search"
    placeholder="Search country, device, browser or link..."
>

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
<td colspan="6">
Waiting for clicks...
</td>
</tr>

</tbody>

</table>

</div>

</div>

</div>


<script>

let events = [];

function renderEvents() {

    const searchInput =
        document.getElementById("search");

    const search =
        searchInput.value.toLowerCase();

    const body =
        document.getElementById("events");

    const filtered =
        events.filter(function(event) {

            const text =
                (
                    event.short_code +
                    " " +
                    event.country +
                    " " +
                    event.device +
                    " " +
                    event.os +
                    " " +
                    event.browser
                ).toLowerCase();

            return text.includes(search);
        });

    if (filtered.length === 0) {

        body.innerHTML =
            "<tr><td colspan='6'>No matching events.</td></tr>";

        return;
    }

    body.innerHTML =
        filtered.map(function(event) {

            const time =
                new Date(
                    event.clicked_at
                ).toLocaleTimeString();

            return `
            <tr>
                <td>${time}</td>
                <td>/${event.short_code}</td>
                <td>${event.country}</td>
                <td>${event.device}</td>
                <td>${event.os}</td>
                <td>${event.browser}</td>
            </tr>
            `;

        }).join("");
}


async function loadEvents() {

    try {

        const response =
            await fetch(
                "/api/live-clicks",
                {
                    cache: "no-store"
                }
            );

        if (!response.ok) {
            return;
        }

        events =
            await response.json();

        renderEvents();

    } catch (error) {

        console.log(
            "Live console error:",
            error
        );
    }
}


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

</body>

</html>
"""


# ============================================================
# SHORT LINK REDIRECT + CLICK TRACKING
# ============================================================

@app.route("/<short_code>")
def redirect_short_link(short_code):

    user_agent = request.headers.get(
        "User-Agent",
        ""
    )

    ip = get_client_ip()

    country = get_country(ip)

    device = get_device(user_agent)

    operating_system = get_operating_system(
        user_agent
    )

    browser = get_browser(
        user_agent
    )

    ip_hash = hash_ip(ip)

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

            if not link:
                abort(404)

            link_id = link[0]

            original_url = link[1]

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
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    link_id,
                    short_code,
                    country,
                    device,
                    operating_system,
                    browser,
                    ip_hash
                )
            )

        conn.commit()

    return redirect(
        original_url
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    try:

        with get_db() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    "SELECT 1"
                )

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
    print("       SHUVO AHMED SMARTLINK")
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

    app.run(
        host="127.0.0.1",
        port=8080,
        debug=True
    )