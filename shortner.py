from flask import Flask, request, redirect, render_template_string, url_for, flash, jsonify
import sqlite3
import string
import random
from datetime import datetime
import urllib.request
import json
import re

app = Flask(__name__)
app.secret_key = "change-this-secret-key-12345"

DB_NAME = "urls.db"

# ============================================================
# LIVE MEMORY
# ============================================================

live_events = []
MAX_LIVE_EVENTS = 100


def add_live_event(event):
    live_events.insert(0, event)

    if len(live_events) > MAX_LIVE_EVENTS:
        del live_events[MAX_LIVE_EVENTS:]


# ============================================================
# DATABASE
# ============================================================

def init_db():

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            short_code TEXT UNIQUE NOT NULL,
            original_url TEXT NOT NULL,
            clicks INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS click_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            short_code TEXT NOT NULL,
            country TEXT,
            device TEXT,
            os TEXT,
            browser TEXT,
            clicked_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def get_db():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row

    return conn


# ============================================================
# SHORT CODE
# ============================================================

def generate_short_code(length=6):

    chars = string.ascii_letters + string.digits

    while True:

        code = "".join(
            random.choice(chars)
            for _ in range(length)
        )

        conn = get_db()

        exists = conn.execute(
            "SELECT id FROM links WHERE short_code = ?",
            (code,)
        ).fetchone()

        conn.close()

        if not exists:
            return code


# ============================================================
# CLIENT IP
# ============================================================

def get_client_ip():

    forwarded = request.headers.get("X-Forwarded-For")

    if forwarded:
        return forwarded.split(",")[0].strip()

    return request.remote_addr or ""


# ============================================================
# COUNTRY LOOKUP
# ============================================================

country_cache = {}


def get_country(ip):

    if not ip:
        return "Unknown"

    if ip in ("127.0.0.1", "::1"):
        return "Local / PC"

    private_ranges = (
        ip.startswith("10."),
        ip.startswith("192.168."),
        ip.startswith("172.16."),
        ip.startswith("172.17."),
        ip.startswith("172.18."),
        ip.startswith("172.19."),
        ip.startswith("172.20."),
        ip.startswith("172.21."),
        ip.startswith("172.22."),
        ip.startswith("172.23."),
        ip.startswith("172.24."),
        ip.startswith("172.25."),
        ip.startswith("172.26."),
        ip.startswith("172.27."),
        ip.startswith("172.28."),
        ip.startswith("172.29."),
        ip.startswith("172.30."),
        ip.startswith("172.31.")
    )

    if any(private_ranges):
        return "Local Network"

    if ip in country_cache:
        return country_cache[ip]

    country = "Unknown"

    try:

        req = urllib.request.Request(
            "https://ipwho.is/" + ip,
            headers={
                "User-Agent": "ShuvoSmartLinkShortener/2.0"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=3
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

            if data.get("success"):
                country = data.get(
                    "country",
                    "Unknown"
                )

    except Exception:
        country = "Unknown"

    country_cache[ip] = country

    return country


# ============================================================
# USER AGENT ANALYSIS
# ============================================================

def detect_device(user_agent):

    ua = user_agent.lower()

    # iPhone
    if "iphone" in ua:
        return "iPhone"

    # iPad
    if "ipad" in ua:
        return "iPad"

    # Android tablets
    if "android" in ua and (
        "tablet" in ua or
        "sm-t" in ua or
        "tab" in ua
    ):
        return "Android Tablet"

    # Android phones
    if "android" in ua:
        return "Android Phone"

    # Mac
    if "macintosh" in ua or "mac os x" in ua:
        return "Mac"

    # Windows PC/Laptop
    if "windows" in ua:
        return "Windows PC"

    # Linux
    if "linux" in ua:
        return "Linux PC"

    # ChromeOS
    if "cros" in ua:
        return "ChromeOS"

    return "Unknown Device"


def detect_os(user_agent):

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

    return "Unknown OS"


def detect_browser(user_agent):

    ua = user_agent.lower()

    if "edg/" in ua:
        return "Microsoft Edge"

    if "opr/" in ua or "opera" in ua:
        return "Opera"

    if "firefox/" in ua:
        return "Firefox"

    if "safari/" in ua and "chrome/" not in ua:
        return "Safari"

    if "chrome/" in ua:
        return "Google Chrome"

    if "samsungbrowser/" in ua:
        return "Samsung Internet"

    return "Unknown Browser"


def device_icon(device):

    if "iPhone" in device:
        return "📱"

    if "iPad" in device or "Tablet" in device:
        return "📲"

    if "Android Phone" in device:
        return "📱"

    if "Mac" in device:
        return "💻"

    if "Windows" in device:
        return "🖥️"

    if "Linux" in device:
        return "💻"

    return "🌐"


# ============================================================
# HOME PAGE
# ============================================================

HOME_TEMPLATE = """
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>Shuvo's Smart Link Shortener</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    min-height: 100vh;

    font-family:
        Inter,
        Arial,
        sans-serif;

    color: #e5e7eb;

    background:
        radial-gradient(
            circle at top left,
            #172554 0,
            #020617 42%,
            #020617 100%
        );
}

.container {
    width: min(900px, 94%);
    margin: auto;
    padding: 70px 0;
}

.brand {
    text-align: center;
    margin-bottom: 35px;
}

.logo {
    width: 76px;
    height: 76px;
    margin: auto;

    display: flex;
    align-items: center;
    justify-content: center;

    border-radius: 22px;

    font-size: 34px;

    background:
        linear-gradient(
            135deg,
            #38bdf8,
            #6366f1
        );

    box-shadow:
        0 25px 70px
        rgba(56,189,248,.25);
}

h1 {
    margin: 18px 0 8px;

    font-size:
        clamp(28px, 5vw, 46px);

    letter-spacing: -1.5px;
}

.subtitle {
    color: #94a3b8;
}

.card {
    background:
        rgba(15,23,42,.82);

    border: 1px solid
        rgba(148,163,184,.12);

    border-radius: 24px;

    padding: 32px;

    box-shadow:
        0 30px 90px
        rgba(0,0,0,.4);

    backdrop-filter: blur(18px);
}

label {
    display: block;

    margin-bottom: 8px;

    color: #cbd5e1;

    font-size: 14px;

    font-weight: 600;
}

input {
    width: 100%;

    padding: 15px 16px;

    margin-bottom: 20px;

    border: 1px solid #334155;

    outline: none;

    border-radius: 12px;

    background: #0f172a;

    color: white;

    font-size: 15px;
}

input:focus {
    border-color: #38bdf8;

    box-shadow:
        0 0 0 3px
        rgba(56,189,248,.10);
}

button {
    width: 100%;

    border: 0;

    border-radius: 12px;

    padding: 15px;

    cursor: pointer;

    color: white;

    font-size: 16px;

    font-weight: 700;

    background:
        linear-gradient(
            135deg,
            #22c55e,
            #06b6d4
        );
}

.result {
    margin-top: 25px;

    padding: 18px;

    border-radius: 14px;

    background: #020617;

    border: 1px solid #1e293b;
}

.result-title {
    color: #94a3b8;

    font-size: 12px;

    margin-bottom: 8px;

    letter-spacing: 1px;
}

.result-row {
    display: flex;

    align-items: center;

    gap: 10px;
}

.result-row a {
    flex: 1;

    color: #38bdf8;

    word-break: break-all;

    text-decoration: none;
}

.copy-btn {
    width: auto;

    padding: 10px 15px;

    background: #1e293b;

    font-size: 13px;
}

.dashboard {
    display: block;

    margin-top: 24px;

    text-align: center;

    color: #94a3b8;

    text-decoration: none;
}

.dashboard:hover {
    color: #38bdf8;
}

.flash {
    padding: 13px;

    margin-bottom: 20px;

    text-align: center;

    border-radius: 10px;

    background: #16a34a;
}

.footer {
    text-align: center;

    color: #64748b;

    font-size: 12px;

    margin-top: 25px;
}

</style>

</head>

<body>

<div class="container">

    <div class="brand">

        <div class="logo">
            🔗
        </div>

        <h1>
            Shuvo's Smart Link Shortener
        </h1>

        <div class="subtitle">
            Smart • Fast • Secure • Professional
        </div>

    </div>


    <div class="card">

        {% with messages = get_flashed_messages() %}

        {% if messages %}

            {% for message in messages %}

                <div class="flash">
                    {{ message }}
                </div>

            {% endfor %}

        {% endif %}

        {% endwith %}


        <form method="POST">

            <label>
                Long URL
            </label>

            <input
                type="url"
                name="url"
                placeholder="https://example.com/your-long-link"
                required
            >


            <label>
                Custom Slug
                <span style="color:#64748b;">
                    (Optional)
                </span>
            </label>

            <input
                type="text"
                name="custom_code"
                placeholder="my-link"
            >


            <button type="submit">
                ✨ Create Smart Link
            </button>

        </form>


        {% if short_url %}

        <div class="result">

            <div class="result-title">
                YOUR SMART LINK
            </div>

            <div class="result-row">

                <a
                    href="{{ short_url }}"
                    target="_blank"
                    id="shortLink"
                >
                    {{ short_url }}
                </a>

                <button
                    type="button"
                    class="copy-btn"
                    onclick="copyLink()"
                >
                    Copy
                </button>

            </div>

        </div>

        {% endif %}


        <a
            href="{{ url_for('dashboard') }}"
            class="dashboard"
        >
            📊 Open Professional Analytics →
        </a>

    </div>


    <div class="footer">
        Shuvo's Smart Link Shortener
    </div>

</div>


<script>

function copyLink() {

    const element =
        document.getElementById("shortLink");

    if (!element) return;

    navigator.clipboard.writeText(
        element.innerText
    );

    alert("Smart link copied!");

}

</script>

</body>

</html>
"""


# ============================================================
# DASHBOARD
# ============================================================

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>Shuvo's Smart Analytics</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;

    background: #020617;

    color: #e5e7eb;

    font-family:
        Inter,
        Arial,
        sans-serif;
}

.wrapper {
    width: min(1350px, 94%);

    margin: auto;

    padding: 32px 0 60px;
}

.header {
    display: flex;

    align-items: center;

    justify-content: space-between;

    gap: 20px;

    margin-bottom: 28px;
}

.brand h1 {
    margin: 0;

    font-size: 29px;
}

.brand p {
    margin: 7px 0 0;

    color: #64748b;
}

.home {
    color: #38bdf8;

    text-decoration: none;

    padding: 10px 15px;

    border: 1px solid #1e293b;

    border-radius: 10px;
}

.stats {
    display: grid;

    grid-template-columns:
        repeat(4, 1fr);

    gap: 16px;

    margin-bottom: 20px;
}

.stat {
    padding: 22px;

    border-radius: 18px;

    background:
        linear-gradient(
            145deg,
            #0f172a,
            #111827
        );

    border: 1px solid #1e293b;
}

.stat-label {
    color: #64748b;

    font-size: 12px;

    letter-spacing: .7px;

    margin-bottom: 9px;
}

.stat-value {
    font-size: 29px;

    font-weight: 800;
}

.grid {
    display: grid;

    grid-template-columns:
        2fr 1fr;

    gap: 20px;

    margin-bottom: 20px;
}

.panel {
    background: #0f172a;

    border: 1px solid #1e293b;

    border-radius: 18px;

    overflow: hidden;
}

.panel-header {
    padding: 17px 20px;

    display: flex;

    align-items: center;

    justify-content: space-between;

    border-bottom: 1px solid #1e293b;
}

.panel-title {
    font-weight: 700;
}

.live {
    display: flex;

    align-items: center;

    gap: 7px;

    color: #22c55e;

    font-size: 11px;

    font-weight: 800;
}

.dot {
    width: 8px;
    height: 8px;

    border-radius: 50%;

    background: #22c55e;

    box-shadow:
        0 0 14px
        rgba(34,197,94,.9);

    animation: pulse 1.4s infinite;
}

@keyframes pulse {

    0% {
        opacity: .35;
    }

    50% {
        opacity: 1;
    }

    100% {
        opacity: .35;
    }
}

.console {
    height: 360px;

    overflow-y: auto;

    padding: 14px 18px;

    background: #010409;

    font-family:
        Consolas,
        monospace;

    font-size: 12px;
}

.event {
    padding: 10px 0;

    border-bottom:
        1px solid
        rgba(30,41,59,.65);

    line-height: 1.6;
}

.time {
    color: #64748b;
}

.link {
    color: #38bdf8;

    font-weight: 700;
}

.country {
    color: #22c55e;

    font-weight: 700;
}

.device {
    color: #f59e0b;

    font-weight: 700;
}

.browser {
    color: #a78bfa;
}

.analytics {
    padding: 18px;
}

.metric-row {
    margin-bottom: 17px;
}

.metric-top {
    display: flex;

    justify-content: space-between;

    margin-bottom: 7px;

    font-size: 13px;
}

.bar {
    height: 7px;

    background: #1e293b;

    border-radius: 10px;

    overflow: hidden;
}

.bar-fill {
    height: 100%;

    background:
        linear-gradient(
            90deg,
            #38bdf8,
            #6366f1
        );

    border-radius: 10px;
}

.table-wrap {
    overflow-x: auto;
}

table {
    width: 100%;

    border-collapse: collapse;
}

th {
    text-align: left;

    padding: 14px 18px;

    color: #64748b;

    font-size: 11px;

    text-transform: uppercase;

    letter-spacing: .6px;
}

td {
    padding: 14px 18px;

    border-top: 1px solid #1e293b;

    font-size: 13px;
}

.code {
    color: #38bdf8;

    font-weight: 700;
}

.empty {
    text-align: center;

    padding: 40px;

    color: #64748b;
}

@media(max-width: 900px) {

    .stats {
        grid-template-columns:
            repeat(2, 1fr);
    }

    .grid {
        grid-template-columns: 1fr;
    }
}

@media(max-width: 550px) {

    .stats {
        grid-template-columns: 1fr;
    }

    .header {
        flex-direction: column;

        align-items: flex-start;
    }
}

</style>

</head>

<body>

<div class="wrapper">


    <div class="header">

        <div class="brand">

            <h1>
                🔗 Shuvo's Smart Analytics
            </h1>

            <p>
                Real-time link performance & visitor insights
            </p>

        </div>


        <a
            href="{{ url_for('home') }}"
            class="home"
        >
            ← Create Link
        </a>

    </div>


    <!-- STATS -->

    <div class="stats">

        <div class="stat">

            <div class="stat-label">
                TOTAL LINKS
            </div>

            <div class="stat-value">
                {{ total_links }}
            </div>

        </div>


        <div class="stat">

            <div class="stat-label">
                TOTAL CLICKS
            </div>

            <div class="stat-value">
                {{ total_clicks }}
            </div>

        </div>


        <div class="stat">

            <div class="stat-label">
                TODAY'S CLICKS
            </div>

            <div class="stat-value">
                {{ today_clicks }}
            </div>

        </div>


        <div class="stat">

            <div class="stat-label">
                ACTIVE LINKS
            </div>

            <div class="stat-value">
                {{ active_links }}
            </div>

        </div>

    </div>


    <div class="grid">


        <!-- LIVE CONSOLE -->

        <div class="panel">

            <div class="panel-header">

                <div class="panel-title">
                    ⚡ Live Click Console
                </div>

                <div class="live">

                    <span class="dot"></span>

                    LIVE

                </div>

            </div>


            <div
                class="console"
                id="liveConsole"
            >

                <div class="event">
                    Waiting for live clicks...
                </div>

            </div>

        </div>


        <!-- TOP ANALYTICS -->

        <div class="panel">

            <div class="panel-header">

                <div class="panel-title">
                    🌍 Top Countries
                </div>

            </div>


            <div class="analytics">

                {% for item in countries %}

                <div class="metric-row">

                    <div class="metric-top">

                        <span>
                            {{ item.country }}
                        </span>

                        <strong>
                            {{ item.total }}
                        </strong>

                    </div>

                    <div class="bar">

                        <div
                            class="bar-fill"
                            style="width: {{ item.percent }}%;"
                        ></div>

                    </div>

                </div>

                {% else %}

                <div class="empty">
                    No data yet.
                </div>

                {% endfor %}

            </div>

        </div>

    </div>


    <!-- DEVICE ANALYTICS -->

    <div class="panel" style="margin-bottom:20px;">

        <div class="panel-header">

            <div class="panel-title">
                📱 Device Breakdown
            </div>

        </div>


        <div class="table-wrap">

            <table>

                <thead>

                    <tr>

                        <th>
                            Device
                        </th>

                        <th>
                            Clicks
                        </th>

                    </tr>

                </thead>


                <tbody>

                    {% for item in devices %}

                    <tr>

                        <td>
                            {{ item.device }}
                        </td>

                        <td>
                            {{ item.total }}
                        </td>

                    </tr>

                    {% else %}

                    <tr>

                        <td
                            colspan="2"
                            class="empty"
                        >
                            No device data yet.
                        </td>

                    </tr>

                    {% endfor %}

                </tbody>

            </table>

        </div>

    </div>


    <!-- RECENT CLICKS -->

    <div class="panel">

        <div class="panel-header">

            <div class="panel-title">
                📊 Recent Visitor Activity
            </div>

        </div>


        <div class="table-wrap">

            <table>

                <thead>

                    <tr>

                        <th>
                            Link
                        </th>

                        <th>
                            Country
                        </th>

                        <th>
                            Device
                        </th>

                        <th>
                            OS
                        </th>

                        <th>
                            Browser
                        </th>

                        <th>
                            Time
                        </th>

                    </tr>

                </thead>


                <tbody>

                    {% for click in recent_clicks %}

                    <tr>

                        <td class="code">
                            /{{ click.short_code }}
                        </td>

                        <td>
                            🌍 {{ click.country }}
                        </td>

                        <td>
                            {{ click.device }}
                        </td>

                        <td>
                            {{ click.os }}
                        </td>

                        <td>
                            {{ click.browser }}
                        </td>

                        <td>
                            {{ click.clicked_at }}
                        </td>

                    </tr>

                    {% else %}

                    <tr>

                        <td
                            colspan="6"
                            class="empty"
                        >
                            No clicks yet.
                        </td>

                    </tr>

                    {% endfor %}

                </tbody>

            </table>

        </div>

    </div>


</div>


<script>

async function updateLive() {

    try {

        const response =
            await fetch(
                "/api/live-events"
            );

        const data =
            await response.json();


        const consoleBox =
            document.getElementById(
                "liveConsole"
            );


        if (!data.events.length) {

            consoleBox.innerHTML = `
                <div class="event">
                    Waiting for live clicks...
                </div>
            `;

            return;
        }


        consoleBox.innerHTML =
            data.events
            .slice(0, 40)
            .map(event => `

                <div class="event">

                    <span class="time">
                        [${event.time}]
                    </span>

                    &nbsp;

                    <span class="link">
                        CLICK /${event.short_code}
                    </span>

                    &nbsp;→&nbsp;

                    <span class="country">
                        🌍 ${event.country}
                    </span>

                    &nbsp;|&nbsp;

                    <span class="device">
                        ${event.device}
                    </span>

                    &nbsp;|&nbsp;

                    <span class="browser">
                        ${event.browser}
                    </span>

                    &nbsp;|&nbsp;

                    ${event.os}

                </div>

            `)
            .join("");

    }

    catch(error) {

        console.log(
            "Live analytics error:",
            error
        );

    }

}


updateLive();

setInterval(
    updateLive,
    2000
);

</script>


</body>

</html>
"""


# ============================================================
# HOME
# ============================================================

@app.route("/", methods=["GET", "POST"])
def home():

    short_url = None

    if request.method == "POST":

        original_url = request.form.get(
            "url",
            ""
        ).strip()

        custom_code = request.form.get(
            "custom_code",
            ""
        ).strip()


        if not original_url:

            flash(
                "Please enter a URL."
            )

            return render_template_string(
                HOME_TEMPLATE
            )


        if custom_code:

            if not re.match(
                r"^[A-Za-z0-9_-]+$",
                custom_code
            ):

                flash(
                    "Custom slug can contain only letters, numbers, - and _."
                )

                return render_template_string(
                    HOME_TEMPLATE
                )

            short_code = custom_code

        else:

            short_code = generate_short_code()


        conn = get_db()


        try:

            conn.execute(
                """
                INSERT INTO links
                (
                    short_code,
                    original_url,
                    created_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    short_code,
                    original_url,
                    datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                )
            )

            conn.commit()


            short_url = (
                request.host_url
                + short_code
            )


            flash(
                "Smart link created successfully!"
            )


        except sqlite3.IntegrityError:

            flash(
                "This slug is already in use."
            )


        finally:

            conn.close()


    return render_template_string(
        HOME_TEMPLATE,
        short_url=short_url
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():

    conn = get_db()


    total_links = conn.execute(
        "SELECT COUNT(*) FROM links"
    ).fetchone()[0]


    total_clicks = conn.execute(
        "SELECT COALESCE(SUM(clicks),0) FROM links"
    ).fetchone()[0]


    today = datetime.now().strftime(
        "%Y-%m-%d"
    )


    today_clicks = conn.execute(
        """
        SELECT COUNT(*)
        FROM click_logs
        WHERE clicked_at LIKE ?
        """,
        (today + "%",)
    ).fetchone()[0]


    active_links = conn.execute(
        """
        SELECT COUNT(*)
        FROM links
        WHERE clicks > 0
        """
    ).fetchone()[0]


    recent_clicks = conn.execute(
        """
        SELECT *
        FROM click_logs
        ORDER BY id DESC
        LIMIT 100
        """
    ).fetchall()


    country_rows = conn.execute(
        """
        SELECT country, COUNT(*) AS total
        FROM click_logs
        GROUP BY country
        ORDER BY total DESC
        LIMIT 8
        """
    ).fetchall()


    device_rows = conn.execute(
        """
        SELECT device, COUNT(*) AS total
        FROM click_logs
        GROUP BY device
        ORDER BY total DESC
        LIMIT 10
        """
    ).fetchall()


    total_for_percent = max(
        total_clicks,
        1
    )


    countries = []

    for row in country_rows:

        percent = (
            row["total"]
            / total_for_percent
        ) * 100

        countries.append({
            "country": row["country"],
            "total": row["total"],
            "percent": round(
                min(percent, 100),
                1
            )
        })


    devices = []

    for row in device_rows:

        devices.append({
            "device": row["device"],
            "total": row["total"]
        })


    conn.close()


    return render_template_string(
        DASHBOARD_TEMPLATE,

        total_links=total_links,

        total_clicks=total_clicks,

        today_clicks=today_clicks,

        active_links=active_links,

        recent_clicks=recent_clicks,

        countries=countries,

        devices=devices
    )


# ============================================================
# LIVE API
# ============================================================

@app.route("/api/live-events")
def live_events_api():

    return jsonify({
        "events": live_events
    })


# ============================================================
# REDIRECT + ANALYTICS
# ============================================================

@app.route("/<short_code>")
def redirect_to_url(short_code):

    conn = get_db()


    link = conn.execute(
        """
        SELECT *
        FROM links
        WHERE short_code = ?
        """,
        (short_code,)
    ).fetchone()


    if not link:

        conn.close()

        return (
            "Link not found 😢",
            404
        )


    # Increase click count

    conn.execute(
        """
        UPDATE links
        SET clicks = clicks + 1
        WHERE short_code = ?
        """,
        (short_code,)
    )


    # Visitor information

    ip = get_client_ip()

    user_agent = request.headers.get(
        "User-Agent",
        ""
    )


    country = get_country(ip)

    device = detect_device(
        user_agent
    )

    os_name = detect_os(
        user_agent
    )

    browser = detect_browser(
        user_agent
    )


    clicked_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


    # Save analytics

    conn.execute(
        """
        INSERT INTO click_logs
        (
            short_code,
            country,
            device,
            os,
            browser,
            clicked_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            short_code,
            country,
            device,
            os_name,
            browser,
            clicked_at
        )
    )


    conn.commit()

    conn.close()


    # Live dashboard event

    event = {

        "short_code":
            short_code,

        "country":
            country,

        "device":
            device,

        "os":
            os_name,

        "browser":
            browser,

        "time":
            clicked_at
    }


    add_live_event(event)


    # CMD live console

    print(
        f"[LIVE CLICK] "
        f"{clicked_at} | "
        f"/{short_code} | "
        f"{country} | "
        f"{device} | "
        f"{os_name} | "
        f"{browser}"
    )


    return redirect(
        link["original_url"]
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    init_db()

    print("=" * 70)

    print(
        "        SHUVO'S SMART LINK SHORTENER"
    )

    print("=" * 70)

    print(
        "Home      : http://127.0.0.1:8080"
    )

    print(
        "Dashboard : http://127.0.0.1:8080/dashboard"
    )

    print("=" * 70)

    print(
        "LIVE ANALYTICS: ACTIVE"
    )

    print(
        "Country + Device + OS + Browser tracking: ACTIVE"
    )

    print("=" * 70)


    app.run(
        debug=True,
        host="127.0.0.1",
        port=8080
    )