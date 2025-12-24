import os
import sqlite3
import qrcode
import csv
import io
import urllib.parse
import datetime
import pytz

from flask import Flask, render_template, request, redirect, session, send_file
from datetime import timedelta

# ---------------- ENV FIX ----------------
os.environ.setdefault("VERCEL", "1")

# ---------------- TIMEZONE ----------------
IST = pytz.timezone("Asia/Kolkata")

# ---------------- FLASK APP ----------------
app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)
app.secret_key = "secret123"
app.permanent_session_lifetime = timedelta(days=1)

# ---------------- PATH HELPERS ----------------
def get_db_path():
    return "/tmp/attendance.db"

def get_tmp_path(filename):
    return os.path.join("/tmp", filename)

# ---------------- DATABASE INIT ----------------
def init_db():
    conn = sqlite3.connect(get_db_path())
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS admin(
            username TEXT,
            password TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS attendance(
            roll TEXT,
            name TEXT,
            date TEXT,
            time TEXT,
            subject TEXT,
            branch TEXT
        )
    """)

    c.execute("INSERT OR IGNORE INTO admin VALUES ('admin','admin123')")
    conn.commit()
    conn.close()

# IMPORTANT: run only once
init_db()

# ---------------- LOGIN ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        conn = sqlite3.connect(get_db_path())
        c = conn.cursor()
        c.execute("SELECT * FROM admin WHERE username=? AND password=?", (u, p))
        if c.fetchone():
            session["admin"] = True
            return redirect("/admin")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect("/")

# ---------------- ADMIN ----------------
@app.route("/admin")
def admin():
    if "admin" not in session:
        return redirect("/")
    return render_template("admin.html")

# ---------------- GENERATE QR ----------------
@app.route("/generate")
def generate():
    if "admin" not in session:
        return redirect("/")

    subject = request.args.get("sub", "")
    branch = request.args.get("branch", "")

    expiry_dt = datetime.datetime.now(IST) + datetime.timedelta(minutes=2)
    expiry = expiry_dt.strftime("%H:%M")

    url = f"{request.host_url}scan?exp={expiry}"
    if subject:
        url += "&sub=" + urllib.parse.quote_plus(subject)
    if branch:
        url += "&branch=" + urllib.parse.quote_plus(branch)

    img = qrcode.make(url)
    img.save(get_tmp_path("qr.png"))

    return render_template(
        "admin.html",
        qr=True,
        expiry=expiry,
        subject=subject,
        branch=branch
    )

@app.route("/static/qr.png")
def serve_qr():
    return send_file(get_tmp_path("qr.png"), mimetype="image/png")

# ---------------- SCAN ----------------
@app.route("/scan", methods=["GET", "POST"])
def scan():
    exp = request.args.get("exp")
    subject = request.args.get("sub")
    branch = request.args.get("branch")

    today = datetime.date.today().isoformat()
    now = datetime.datetime.now(IST).strftime("%H:%M")

    if exp and now > exp:
        return "QR Expired ❌"

    session_key = f"{today}_{subject}_{branch}"
    if session.get(session_key):
        return "Attendance already marked ⚠️"

    if request.method == "POST":
        roll = request.form["roll"]
        name = request.form["name"]
        time = datetime.datetime.now(IST).strftime("%H:%M:%S")

        conn = sqlite3.connect(get_db_path())
        c = conn.cursor()

        c.execute("""
            SELECT * FROM attendance
            WHERE roll=? AND date=? AND subject=? AND branch=?
        """, (roll, today, subject, branch))

        if c.fetchone():
            conn.close()
            session[session_key] = True
            return "Attendance already marked ⚠️"

        c.execute("""
            INSERT INTO attendance
            VALUES (?,?,?,?,?,?)
        """, (roll, name, today, time, subject, branch))

        conn.commit()
        conn.close()

        session[session_key] = True
        session.permanent = True
        return render_template("success.html")

    return render_template("scan.html")

# ---------------- VIEW ----------------
@app.route("/view")
def view():
    if "admin" not in session:
        return redirect("/")

    conn = sqlite3.connect(get_db_path())
    c = conn.cursor()
    c.execute("SELECT * FROM attendance ORDER BY date DESC, time DESC")
    data = c.fetchall()
    conn.close()

    return render_template("view.html", data=data)

# ---------------- EXPORT ----------------
@app.route("/export")
def export():
    conn = sqlite3.connect(get_db_path())
    c = conn.cursor()
    c.execute("SELECT * FROM attendance")
    data = c.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Roll", "Name", "Date", "Time", "Subject", "Branch"])
    writer.writerows(data)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="attendance.csv"
    )
