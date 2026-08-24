import os
import random
import string
from datetime import datetime, timezone

import psycopg
from dotenv import load_dotenv
from flask import Flask, request, redirect, render_template_string, jsonify, abort

load_dotenv()

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")


# ============================================================
# DATABASE
# ============================================================

def get_db():
    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def init_db():

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    id BIGSERIAL PRIMARY KEY,
                    short_code TEXT UNIQUE NOT NULL,
                    original_url TEXT NOT NULL,
                    clicks BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS click_logs (
                    id BIGSERIAL PRIMARY KEY,
                    link_id BIGINT NOT NULL REFERENCES links(id)
                        ON DELETE CASCADE,
                    short_code TEXT NOT NULL,
                    country TEXT,
                    device TEXT,
                    os TEXT,
                    browser TEXT,
                    ip_hash TEXT,
                    clicked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
                    """
                    SELECT 1
                    FROM links
                    WHERE short_code = %s
                    """,
                    (code,)
                )

                if cur.fetchone() is None:
                    return code


# ============================================================
# HOME
# ============================================================

HOME_TEMPLATE = """
<!doctype html>

<html>

<head>

    <meta charset="utf-8">

    <meta name="viewport"
          content="width=device-width, initial-scale=1">

    <title>Shuvo Ahmed SmartLink</title>

</head>

<body>

    <h1>Shuvo Ahmed SmartLink</h1>

    <form method="POST">

        <input
            type="url"
            name="url"
            placeholder="Enter long URL"
            required
        >

        <button type="submit">
            Shorten URL
        </button>

    </form>


    {% if short_url %}

        <hr>

        <p>Your short link:</p>

        <a href="{{ short_url }}"
           target="_blank">

            {{ short_url }}

        </a>

    {% endif %}

</body>

</html>
"""


@app.route("/", methods=["GET", "POST"])
def home():

    short_url = None

    if request.method == "POST":

        original_url = request.form.get(
            "url",
            ""
        ).strip()

        if not original_url.startswith(
            ("http://", "https://")
        ):

            return (
                "Please enter a valid HTTP/HTTPS URL.",
                400
            )

        short_code = generate_short_code()

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO links
                    (
                        short_code,
                        original_url
                    )
                    VALUES (%s, %s)
                    """,
                    (
                        short_code,
                        original_url
                    )
                )

            conn.commit()

        short_url = (
            request.host_url
            + short_code
        )

    return render_template_string(
        HOME_TEMPLATE,
        short_url=short_url
    )


# ============================================================
# REDIRECT
# ============================================================

@app.route("/<short_code>")
def redirect_to_url(short_code):

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT id, original_url
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

        conn.commit()

    return redirect(original_url)


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    try:

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute("SELECT 1")

                result = cur.fetchone()

        return jsonify({
            "status": "ok",
            "database": result[0] == 1
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "database": False
        }), 500


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    init_db()

    app.run(
        host="127.0.0.1",
        port=8080,
        debug=True
    )