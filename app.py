from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import os
import base64
import pandas as pd
from datetime import datetime

app = Flask(__name__)
app.secret_key = "mysecretkey"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024


def init_db():
    conn = sqlite3.connect("attendance.db")
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER,
        date TEXT,
        time TEXT,
        status TEXT,
        latitude TEXT,
        longitude TEXT,
        selfie_path TEXT
    )
    """)

    try:
        df = pd.read_excel("employees.xlsx")

        for _, row in df.iterrows():
            employee_id = int(row["Matricule"])
            employee_name = str(row["Nom & Prénom"]).strip()

            cur.execute("""
                INSERT OR IGNORE INTO employees (id, name)
                VALUES (?, ?)
            """, (employee_id, employee_name))

    except Exception as e:
        print("Error importing employees from Excel:", e)

    conn.commit()
    conn.close()

@app.before_request
def setup_once():
    init_db()
@app.route("/", methods=["GET", "POST"])
def index():
    message = ""

    if request.method == "POST":
        employee_id = request.form["employee_id"]

        conn = sqlite3.connect("attendance.db")
        cur = conn.cursor()
        cur.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
        employee = cur.fetchone()
        conn.close()

        if employee:
            return render_template("checkin.html", employee_id=employee_id)
        else:
            message = "Employee ID is incorrect."

    return render_template("index.html", message=message)


@app.route("/verify", methods=["POST"])
def verify():
    employee_id = request.form["employee_id"]
    entered_code = request.form["code"]

    # kept only so route exists if any old page still posts here
    # right now the main flow goes directly from index -> checkin
    return render_template("checkin.html", employee_id=employee_id)


@app.route("/login", methods=["GET", "POST"])
def login():
    message = ""

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == "admin" and password == "1234":
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))
        else:
            message = "Wrong username or password."

    return render_template("login.html", message=message)


@app.route("/admin")
def admin():
    if not session.get("admin_logged_in"):
        return redirect(url_for("login"))

    conn = sqlite3.connect("attendance.db")
    cur = conn.cursor()

    today = datetime.now().strftime("%Y-%m-%d")

    cur.execute("""
        SELECT employees.id,
               employees.name,
               attendance.date,
               attendance.time,
               attendance.status,
               attendance.latitude,
               attendance.longitude,
               attendance.selfie_path
        FROM attendance
        JOIN employees ON attendance.employee_id = employees.id
        WHERE attendance.date = ? AND attendance.status = 'Present'
        ORDER BY attendance.time DESC
    """, (today,))
    present_records = cur.fetchall()

    cur.execute("""
        SELECT employees.id,
               employees.name,
               attendance.date,
               attendance.time,
               attendance.status,
               attendance.latitude,
               attendance.longitude,
               attendance.selfie_path
        FROM attendance
        JOIN employees ON attendance.employee_id = employees.id
        WHERE attendance.date = ? AND attendance.status = 'Absent'
        ORDER BY attendance.time DESC
    """, (today,))
    absent_records = cur.fetchall()

    conn.close()

    return render_template(
        "admin.html",
        present_records=present_records,
        absent_records=absent_records,
        today=today
    )


@app.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("login"))


@app.route("/employees", methods=["GET", "POST"])
def employees():
    if not session.get("admin_logged_in"):
        return redirect(url_for("login"))

    message = ""

    conn = sqlite3.connect("attendance.db")
    cur = conn.cursor()

    if request.method == "POST":
        employee_id = request.form["employee_id"]
        name = request.form["name"]

        try:
            cur.execute("INSERT INTO employees (id, name) VALUES (?, ?)", (employee_id, name))
            conn.commit()
            message = "Employee added successfully."
        except sqlite3.IntegrityError:
            message = "This employee ID already exists."

    cur.execute("SELECT id, name FROM employees ORDER BY id")
    all_employees = cur.fetchall()
    conn.close()

    return render_template("employees.html", employees=all_employees, message=message)


@app.route("/finalize_checkin", methods=["POST"])
def finalize_checkin():
    employee_id = request.form["employee_id"]
    latitude = request.form["latitude"]
    longitude = request.form["longitude"]
    selfie_data = request.form["selfie_data"]

    if not latitude or not longitude:
        return "<h1>Location is required.</h1><a href='/'>Go back</a>"

    if not selfie_data:
        return "<h1>Selfie is required.</h1><a href='/'>Go back</a>"

    office_lat = 34.020882
    office_lng = -6.841650

    lat = float(latitude)
    lng = float(longitude)

    header, encoded = selfie_data.split(",", 1)
    image_bytes = base64.b64decode(encoded)

    filename = f"employee_{employee_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"

    selfies_folder = os.path.join(app.root_path, "static", "selfies")
    os.makedirs(selfies_folder, exist_ok=True)

    full_filepath = os.path.join(selfies_folder, filename)
    filepath = f"static/selfies/{filename}"

    with open(full_filepath, "wb") as f:
        f.write(image_bytes)

    conn = sqlite3.connect("attendance.db")
    cur = conn.cursor()

    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M:%S")

    cur.execute(
        "SELECT * FROM attendance WHERE employee_id = ? AND date = ?",
        (employee_id, today)
    )
    already_checked = cur.fetchone()

    if already_checked:
        conn.close()
        return "<h1>Attendance already recorded for today.</h1><a href='/'>Go back</a>"

    if abs(lat - office_lat) <= 0.01 and abs(lng - office_lng) <= 0.01:
        status = "Present"
    else:
        status = "Absent"

    cur.execute(
        """
        INSERT INTO attendance (employee_id, date, time, status, latitude, longitude, selfie_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (employee_id, today, now_time, status, latitude, longitude, filepath)
    )

    conn.commit()
    conn.close()

    return f"<h1>Attendance recorded: {status}</h1><a href='/'>Go back</a>"



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
