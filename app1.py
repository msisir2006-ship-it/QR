from flask import Flask, render_template, request, redirect, session, send_file
import sqlite3, qrcode, datetime, csv, io, os
import urllib.parse
from datetime import timedelta

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

    # Ensure attendance table exists without an id column
    c.execute("""
    CREATE TABLE IF NOT EXISTS attendance(
        roll TEXT,
        name TEXT,
        date TEXT,
        time TEXT
    )
    """)

    # Migrate existing old table (with id) to new schema while preserving data
    c.execute("PRAGMA table_info(attendance)")
    cols = [r[1] for r in c.fetchall()]
    # If an 'id' column exists in the real table, it means this table was created with the old schema
    # In that case create a new table migration target and copy data over
    if 'id' in cols:
        c.execute("CREATE TABLE IF NOT EXISTS attendance_new(roll TEXT, name TEXT, date TEXT, time TEXT)")
        c.execute("INSERT INTO attendance_new(roll,name,date,time) SELECT roll,name,date,time FROM attendance")
        c.execute("DROP TABLE attendance")
        c.execute("ALTER TABLE attendance_new RENAME TO attendance")

    # Ensure subject column exists; if not, add it
    if 'subject' not in cols:
        try:
            c.execute("ALTER TABLE attendance ADD COLUMN subject TEXT")
        except Exception:
            # If ALTER fails (e.g., older SQLite), ignore — table will still work without subject
            pass

    # Ensure branch column exists; if not, add it
    if 'branch' not in cols:
        try:
            c.execute("ALTER TABLE attendance ADD COLUMN branch TEXT")
        except Exception:
            # If ALTER fails (e.g., older SQLite), ignore — table will still work without branch
            pass

    c.execute("INSERT OR IGNORE INTO admin VALUES('admin','admin123')")
    # Normalize legacy subject value 'P&S' to 'P and S' so old records update automatically
    try:
        c.execute("UPDATE attendance SET subject = ? WHERE subject = ?", ('P and S', 'P&S'))
    except Exception:
        pass
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

# ---------- ADMIN DASHBOARD ----------
@app.route("/admin")
def admin():
    if "admin" not in session:
        return redirect("/")
    added = request.args.get('added') or ''
    return render_template("admin.html", added=added)

@app.route("/logout")
def logout():
    # Clear admin session and redirect to login
    session.pop("admin", None)
    return redirect("/")

# ---------- GENERATE QR ----------
@app.route("/generate")
def generate():
    if "admin" not in session:
        return redirect("/")
    subject = request.args.get('sub','')
    branch = request.args.get('branch','')
    expiry_dt = datetime.datetime.now() + datetime.timedelta(minutes=2)
    expiry = expiry_dt.strftime("%H:%M")
    expiry_ts = int(expiry_dt.timestamp())
    url = f"{request.host_url}scan?exp={expiry}"
    if subject:
        url += f"&sub={urllib.parse.quote_plus(subject)}"
    if branch:
        url += f"&branch={urllib.parse.quote_plus(branch)}"

    qr_ok = False
    qr_error = None
    try:
        img = qrcode.make(url)
        img.save(get_static_path("qr.png"))
        qr_ok = True
    except Exception as e:
        qr_error = str(e)
        qr_ok = False

    return render_template("admin.html", qr=qr_ok, expiry=expiry, subject=subject, branch=branch, expiry_ts=expiry_ts, qr_error=qr_error)

# ---------- SERVE QR IMAGE ----------
@app.route("/static/qr.png")
def serve_qr():
    qr_path = get_static_path("qr.png")
    if os.path.exists(qr_path):
        return send_file(qr_path, mimetype='image/png')
    return "QR not found", 404

# ---------- SERVE BACKUP FILES ----------
@app.route("/static/backups/<filename>")
def serve_backup(filename):
    backup_path = os.path.join(get_static_path("backups"), filename)
    if os.path.exists(backup_path):
        return send_file(backup_path, mimetype='text/csv', as_attachment=True, download_name=filename)
    return "Backup not found", 404

# ---------- SCAN & MARK ----------
@app.route("/scan", methods=["GET", "POST"])
def scan():
    exp = request.args.get("exp")
    subj = request.args.get("sub") or None
    branch = request.args.get("branch") or None
    date = datetime.date.today().isoformat()
    now = datetime.datetime.now().strftime("%H:%M")

    if exp and now > exp:
        return "QR Expired ❌"

    # Check session to prevent multiple attempts from same device for this subject/branch today
    session_key = f"marked_{date}_{subj if subj else 'general'}_{branch if branch else 'general'}"
    if session.get(session_key):
        return "Attendance Already Marked for this Subject/Branch Today ⚠️"

    if request.method == "POST":
        roll = request.form["roll"]
        name = request.form["name"]
        subj = request.args.get("sub") or request.form.get("subject") or None
        branch = request.args.get("branch") or request.form.get("branch") or None
        time = datetime.datetime.now().strftime("%H:%M:%S")

        conn = sqlite3.connect(get_db_path())
        c = conn.cursor()

        # Check for duplicate: based on available columns
        c.execute("PRAGMA table_info(attendance)")
        cols = [r[1] for r in c.fetchall()]
        if subj and branch and 'subject' in cols and 'branch' in cols:
            c.execute("SELECT * FROM attendance WHERE roll=? AND date=? AND subject=? AND branch=?", (roll, date, subj, branch))
        elif subj and 'subject' in cols:
            c.execute("SELECT * FROM attendance WHERE roll=? AND date=? AND subject=?", (roll, date, subj))
        elif branch and 'branch' in cols:
            c.execute("SELECT * FROM attendance WHERE roll=? AND date=? AND branch=?", (roll, date, branch))
        else:
            c.execute("SELECT * FROM attendance WHERE roll=? AND date=?", (roll, date))
        if c.fetchone():
            session[session_key] = True
            session.permanent = True
            session.permanent = True
            return "Attendance Already Marked ⚠️"

        # Insert including available columns
        if 'subject' in cols and 'branch' in cols:
            c.execute("INSERT INTO attendance (roll, name, date, time, subject, branch) VALUES (?,?,?,?,?,?)",
                      (roll, name, date, time, subj, branch))
        elif 'subject' in cols:
            c.execute("INSERT INTO attendance (roll, name, date, time, subject) VALUES (?,?,?,?,?)",
                      (roll, name, date, time, subj))
        elif 'branch' in cols:
            c.execute("INSERT INTO attendance (roll, name, date, time, branch) VALUES (?,?,?,?,?)",
                      (roll, name, date, time, branch))
        else:
            c.execute("INSERT INTO attendance (roll, name, date, time) VALUES (?,?,?,?)",
                      (roll, name, date, time))
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
    selected_subject = request.args.get('sub') or ''
    selected_branch = request.args.get('branch') or ''
    subjects = ["ML","DBMS","DLCO","P and S","MEFA","ML LAB","DBMS LAB","FULL STACK LAB","DT and I LAB"]
    branches = ["CAI", "CSM", "CSD", "CSE-A", "CSE-B", "CSE-C", "CSE-D", "MECH", "EEE", "ECE", "CIVIL"]

    conn = sqlite3.connect(get_db_path())
    c = conn.cursor()
    if selected_subject and selected_branch:
        c.execute("SELECT * FROM attendance WHERE subject=? AND branch=? ORDER BY date DESC, time DESC", (selected_subject, selected_branch))
    elif selected_subject:
        c.execute("SELECT * FROM attendance WHERE subject=? ORDER BY date DESC, time DESC", (selected_subject,))
    elif selected_branch:
        c.execute("SELECT * FROM attendance WHERE branch=? ORDER BY date DESC, time DESC", (selected_branch,))
    else:
        c.execute("SELECT * FROM attendance ORDER BY date DESC, time DESC")
    data = c.fetchall()
    conn.close()
    cleared = request.args.get('cleared')
    backup = request.args.get('backup')
    added = request.args.get('added') or ''
    return render_template("view.html", data=data, cleared=cleared, backup=backup, subjects=subjects, selected_subject=selected_subject, branches=branches, selected_branch=selected_branch, added=added)

# ---------- MANUAL ADD ATTENDANCE ----------
@app.route("/manual_add", methods=["POST"])
def manual_add():
    if "admin" not in session:
        return redirect("/")
    roll = (request.form.get("roll") or "").strip()
    name = (request.form.get("name") or "").strip()
    subj = request.form.get("subject") or None
    branch = request.form.get("branch") or None
    date = request.form.get("date") or datetime.date.today().isoformat()
    time = request.form.get("time") or datetime.datetime.now().strftime("%H:%M:%S")

    if not roll or not name:
        return redirect(f"/admin?added=error")

    conn = sqlite3.connect(get_db_path())
    c = conn.cursor()
    c.execute("PRAGMA table_info(attendance)")
    cols = [r[1] for r in c.fetchall()]

    # Duplicate check similar to /scan
    if subj and branch and 'subject' in cols and 'branch' in cols:
        c.execute("SELECT * FROM attendance WHERE roll=? AND date=? AND subject=? AND branch=?", (roll, date, subj, branch))
    elif subj and 'subject' in cols:
        c.execute("SELECT * FROM attendance WHERE roll=? AND date=? AND subject=?", (roll, date, subj))
    elif branch and 'branch' in cols:
        c.execute("SELECT * FROM attendance WHERE roll=? AND date=? AND branch=?", (roll, date, branch))
    else:
        c.execute("SELECT * FROM attendance WHERE roll=? AND date=?", (roll, date))
    if c.fetchone():
        conn.close()
        return redirect(f"/admin?added=exists")

    # Insert including available columns
    if 'subject' in cols and 'branch' in cols:
        c.execute("INSERT INTO attendance (roll, name, date, time, subject, branch) VALUES (?,?,?,?,?,?)",
                  (roll, name, date, time, subj, branch))
    elif 'subject' in cols:
        c.execute("INSERT INTO attendance (roll, name, date, time, subject) VALUES (?,?,?,?,?)",
                  (roll, name, date, time, subj))
    elif 'branch' in cols:
        c.execute("INSERT INTO attendance (roll, name, date, time, branch) VALUES (?,?,?,?,?)",
                  (roll, name, date, time, branch))
    else:
        c.execute("INSERT INTO attendance (roll, name, date, time) VALUES (?,?,?,?)",
                  (roll, name, date, time))
    conn.commit()
    conn.close()
    return redirect(f"/admin?added=1")

# ---------- DELETE RECORD ----------
@app.route("/delete")
def delete():
    if "admin" not in session:
        return redirect("/")
    roll = request.args.get("roll")
    date = request.args.get("date")
    time = request.args.get("time")
    subject = request.args.get("subject")
    if not (roll and date and time):
        return redirect("/view")
    conn = sqlite3.connect("attendance.db")
    c = conn.cursor()
    if subject:
        c.execute("DELETE FROM attendance WHERE roll=? AND date=? AND time=? AND subject=?", (roll, date, time, subject))
    else:
        c.execute("DELETE FROM attendance WHERE roll=? AND date=? AND time=?", (roll, date, time))
    conn.commit()
    conn.close()
    # preserve subject filter when redirecting
    if subject:
        return redirect(f"/view?sub={urllib.parse.quote_plus(subject)}")
    return redirect("/view")

# ---------- CLEAR ALL ATTENDANCE ----------
@app.route("/clear_all", methods=["POST"])
def clear_all():
    if "admin" not in session:
        return redirect("/")
    subject = request.form.get('subject') or ''
    branch = request.form.get('branch') or ''
    conn = sqlite3.connect(get_db_path())
    c = conn.cursor()
    if subject and branch:
        c.execute("SELECT * FROM attendance WHERE subject=? AND branch=?", (subject, branch))
    elif subject:
        c.execute("SELECT * FROM attendance WHERE subject=?", (subject,))
    elif branch:
        c.execute("SELECT * FROM attendance WHERE branch=?", (branch,))
    else:
        c.execute("SELECT * FROM attendance")
    data = c.fetchall()
    backup_name = ''
    if data:
        os.makedirs(get_static_path("backups"), exist_ok=True)
        backup_name = datetime.datetime.now().strftime(f"attendance_{subject}_{branch}_backup_%Y%m%d_%H%M%S.csv") if subject and branch else datetime.datetime.now().strftime(f"attendance_{subject or branch}_backup_%Y%m%d_%H%M%S.csv") if subject or branch else datetime.datetime.now().strftime("attendance_backup_%Y%m%d_%H%M%S.csv")
        backup_path = os.path.join(get_static_path("backups"), backup_name)
        with open(backup_path, "w", newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # include columns if present
            if data and len(data[0]) > 4:
                writer.writerow(["Roll", "Name", "Subject", "Date", "Time"])
            else:
                writer.writerow(["Roll", "Name", "Date", "Time"])
            writer.writerows(data)
    if subject and branch:
        c.execute("DELETE FROM attendance WHERE subject=? AND branch=?", (subject, branch))
    elif subject:
        c.execute("DELETE FROM attendance WHERE subject=?", (subject,))
    elif branch:
        c.execute("DELETE FROM attendance WHERE branch=?", (branch,))
    else:
        c.execute("DELETE FROM attendance")
    conn.commit()
    conn.close()
    if backup_name:
        return redirect(f"/view?cleared=1&backup={urllib.parse.quote_plus(backup_name)}&sub={urllib.parse.quote_plus(subject)}&branch={urllib.parse.quote_plus(branch)}")
    else:
        return redirect(f"/view?cleared=2&sub={urllib.parse.quote_plus(subject)}&branch={urllib.parse.quote_plus(branch)}")

# ---------- EXPORT CSV ----------
@app.route("/export")
def export():
    selected_subject = request.args.get('sub') or ''
    selected_branch = request.args.get('branch') or ''
    conn = sqlite3.connect(get_db_path())
    c = conn.cursor()
    if selected_subject and selected_branch:
        c.execute("SELECT * FROM attendance WHERE subject=? AND branch=? ORDER BY date DESC, time DESC", (selected_subject, selected_branch))
    elif selected_subject:
        c.execute("SELECT * FROM attendance WHERE subject=? ORDER BY date DESC, time DESC", (selected_subject,))
    elif selected_branch:
        c.execute("SELECT * FROM attendance WHERE branch=? ORDER BY date DESC, time DESC", (selected_branch,))
    else:
        c.execute("SELECT * FROM attendance ORDER BY date DESC, time DESC")
    data = c.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    # Include headers based on available columns
    header = ["Roll", "Name", "Date", "Time"]
    if data and len(data[0]) > 4:
        header.insert(2, "Subject")
    if data and len(data[0]) > 5:
        header.insert(3, "Branch")
    writer.writerow(header)
    writer.writerows(data)

    filename = "attendance.csv"
    if selected_subject:
        filename = f"attendance_{selected_subject}.csv"
    if selected_branch:
        filename = f"attendance_{selected_branch}.csv"

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)