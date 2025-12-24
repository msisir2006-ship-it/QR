from flask import Flask, render_template, request, redirect, session, send_file
import sqlite3, qrcode, datetime, csv, io, os
import urllib.parse
from datetime import timedelta
import pytz

# ---------------- TIMEZONE FIX ----------------
IST = pytz.timezone("Asia/Kolkata")

app = Flask(__name__)
app.secret_key = "secret123"
app.permanent_session_lifetime = timedelta(days=1)

def get_db_path():
    return os.path.join("/tmp", "attendance.db") if os.environ.get('VERCEL') else "attendance.db"

def get_static_path(filename=""):
    base = "/tmp" if os.environ.get('VERCEL') else "static"
    return os.path.join(base, filename) if filename else base

# ---------- DATABASE SETUP ----------
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

    c.execute("INSERT OR IGNORE INTO admin VALUES('admin','admin123')")
    conn.commit()
    conn.close()

init_db()

# ---------- LOGIN ----------
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

# ---------- ADMIN ----------
@app.route("/admin")
def admin():
    if "admin" not in session:
        return redirect("/")
    return render_template("admin.html")

@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect("/")

# ---------- GENERATE QR ----------
@app.route("/generate")
def generate():
    if "admin" not in session:
        return redirect("/")

    subject = request.args.get('sub', '')
    branch = request.args.get('branch', '')

    expiry_dt = datetime.datetime.now(IST) + datetime.timedelta(minutes=2)
    expiry = expiry_dt.strftime("%H:%M")

    url = f"{request.host_url}scan?exp={expiry}"
    if subject:
        url += f"&sub={urllib.parse.quote_plus(subject)}"
    if branch:
        url += f"&branch={urllib.parse.quote_plus(branch)}"

    img = qrcode.make(url)
    img.save(get_static_path("qr.png"))

    return render_template(
        "admin.html",
        qr=True,
        expiry=expiry,
        subject=subject,
        branch=branch
    )

# ---------- SERVE QR ----------
@app.route("/static/qr.png")
def serve_qr():
    qr_path = get_static_path("qr.png")
    return send_file(qr_path, mimetype="image/png")

# ---------- SCAN ----------
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
        (roll, name, date, time, subject, branch)
        VALUES (?,?,?,?,?,?)
        """, (roll, name, today, time, subject, branch))

        conn.commit()
        conn.close()

        session[session_key] = True
        session.permanent = True
        return render_template("success.html")

    return render_template("scan.html")

# ---------- VIEW ----------
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

# ---------- EXPORT CSV ----------
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

# ---------- RUN ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
