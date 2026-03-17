from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import os
import base64
import pandas as pd
import math
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "amine2004"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

db_initialized = False

# -----------------------------
# SETTINGS
# -----------------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "amine2004"

ATTENDANCE_START = "08:00"
ATTENDANCE_END = "17:00"

# Tolerance radius in meters
# Increase or decrease this if you want
ATTENDANCE_RADIUS_METERS = 1000

CITY_COORDS = {
    "MIDELT": (32.6794074, -4.7391958),
    "RICH": (32.2597162, -4.5034973),
    "GOURRAMA": (32.3373380, -4.0666185),
    "BOUMIA": (32.7253792, -5.1087271),
    "ITZER": (32.8786707, -5.0466128),
}

# if your Excel uses one of these headers for city, it will work
POSSIBLE_CITY_COLUMNS = [
    "Ville",
    "ville",
    "City",
    "city",
    "Localité",
    "localité",
    "Localite",
    "localite",
    "Affectation",
    "affectation",
    "Centre",
    "centre",
    "Bureau",
    "bureau",
    "Lieu",
    "lieu",
    "Site",
    "site",
]


# -----------------------------
# HELPERS
# -----------------------------
def normalize_city(city_value):
    if city_value is None:
        return ""
    city = str(city_value).strip().upper()

    aliases = {
        "MIDELT": "MIDELT",
        "RICH": "RICH",
        "GOURRAMA": "GOURRAMA",
        "BOUMIA": "BOUMIA",
        "ITZER": "ITZER",
    }

    return aliases.get(city, city)


def extract_city_from_row(row):
    for col in POSSIBLE_CITY_COLUMNS:
        if col in row and pd.notna(row[col]):
            return normalize_city(row[col])
    return ""


def haversine_meters(lat1, lon1, lat2, lon2):
    r = 6371000  # earth radius in meters

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return r * c


def is_within_allowed_area(employee_city, user_lat, user_lng):
    employee_city = normalize_city(employee_city)
    if employee_city not in CITY_COORDS:
        return False

    office_lat, office_lng = CITY_COORDS[employee_city]
    distance = haversine_meters(user_lat, user_lng, office_lat, office_lng)
    return distance <= ATTENDANCE_RADIUS_METERS


def get_time_window():
    start_time = datetime.strptime(ATTENDANCE_START, "%H:%M").time()
    end_time = datetime.strptime(ATTENDANCE_END, "%H:%M").time()
    return start_time, end_time


# -----------------------------
# DB
# -----------------------------
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

    # Add city column if it doesn't exist yet
    cur.execute("PRAGMA table_info(employees)")
    columns = [row[1] for row in cur.fetchall()]
    if "city" not in columns:
        cur.execute("ALTER TABLE employees ADD COLUMN city TEXT")

    # Import from Excel if file exists
    try:
        df = pd.read_excel("employees.xlsx")

        for _, row in df.iterrows():
            employee_id = int(row["Matricule"])
            employee_name = str(row["Nom & Prénom"]).strip()
            employee_city = extract_city_from_row(row)

            cur.execute("""
                INSERT INTO employees (id, name, city)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    city = excluded.city
            """, (employee_id, employee_name, employee_city))

    except Exception as e:
        print("Excel import skipped or failed:", e)

    conn.commit()
    conn.close()


def ensure_db_initialized():
    global db_initialized
    if not db_initialized:
        init_db()
        db_initialized = True


def ensure_daily_absences():
    ensure_db_initialized()

    now = datetime.now()
    current_time = now.time()
    _, end_time = get_time_window()

    # only generate auto-absences after 10:00
    if current_time < end_time:
        return

    today = now.strftime("%Y-%m-%d")

    conn = sqlite3.connect("attendance.db")
    cur = conn.cursor()

    cur.execute("SELECT id FROM employees")
    all_employees = cur.fetchall()

    for employee in all_employees:
        employee_id = employee[0]

        cur.execute("""
            SELECT 1 FROM attendance
            WHERE employee_id = ? AND date = ?
        """, (employee_id, today))
        exists = cur.fetchone()

        if not exists:
            cur.execute("""
                INSERT INTO attendance (employee_id, date, time, status, latitude, longitude, selfie_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                employee_id,
                today,
                ATTENDANCE_END + ":00",
                "Absent",
                "Not provided",
                "Not provided",
                ""
            ))

    conn.commit()
    conn.close()


# -----------------------------
# ROUTES
# -----------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    ensure_db_initialized()
    ensure_daily_absences()

    message = ""

    if request.method == "POST":
        employee_id = request.form["employee_id"]

        conn = sqlite3.connect("attendance.db")
        cur = conn.cursor()
        cur.execute("SELECT id, name, city FROM employees WHERE id = ?", (employee_id,))
        employee = cur.fetchone()
        conn.close()

        if employee:
            return render_template("checkin.html", employee_id=employee_id)
        else:
            message = "Employee ID is incorrect."

    return render_template("index.html", message=message)


@app.route("/login", methods=["GET", "POST"])
def login():
    ensure_db_initialized()
    ensure_daily_absences()

    message = ""

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))
        else:
            message = "Wrong username or password."

    return render_template("login.html", message=message)


@app.route("/admin")
def admin():
    ensure_db_initialized()
    ensure_daily_absences()

    if not session.get("admin_logged_in"):
        return redirect(url_for("login"))

    conn = sqlite3.connect("attendance.db")
    cur = conn.cursor()

    today = datetime.now().strftime("%Y-%m-%d")

    cur.execute("""
        SELECT employees.id,
               employees.name,
               employees.city,
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
               employees.city,
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
    ensure_db_initialized()

    if not session.get("admin_logged_in"):
        return redirect(url_for("login"))

    message = ""

    conn = sqlite3.connect("attendance.db")
    cur = conn.cursor()

    if request.method == "POST":
        employee_id = request.form["employee_id"]
        name = request.form["name"]
        city = normalize_city(request.form["city"])

        try:
            cur.execute("""
                INSERT INTO employees (id, name, city)
                VALUES (?, ?, ?)
            """, (employee_id, name, city))
            conn.commit()
            message = "Employee added successfully."
        except sqlite3.IntegrityError:
            message = "This employee ID already exists."

    cur.execute("SELECT id, name, city FROM employees ORDER BY city, id")
    all_employees = cur.fetchall()
    conn.close()

    return render_template(
        "employees.html",
        employees=all_employees,
        message=message,
        cities=sorted(CITY_COORDS.keys())
    )

@app.route("/finalize_checkin", methods=["POST"])
def finalize_checkin():
    ensure_db_initialized()
    ensure_daily_absences()

    employee_id = request.form["employee_id"]
    latitude = request.form["latitude"]
    longitude = request.form["longitude"]
    selfie_data = request.form["selfie_data"]

    if not latitude or not longitude:
        return "<h1>Location is required.</h1><a href='/'>Go back</a>"

    if not selfie_data:
        return "<h1>Selfie is required.</h1><a href='/'>Go back</a>"

    conn = sqlite3.connect("attendance.db")
    cur = conn.cursor()

    cur.execute("SELECT name, city FROM employees WHERE id = ?", (employee_id,))
    employee = cur.fetchone()

    if not employee:
        conn.close()
        return "<h1>Employee not found.</h1><a href='/'>Go back</a>"

    employee_name, employee_city = employee

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    now_time = now.strftime("%H:%M:%S")
    current_time = now.time()

    start_time, end_time = get_time_window()

    # prevent duplicate attendance for same day
    cur.execute("""
        SELECT * FROM attendance
        WHERE employee_id = ? AND date = ?
    """, (employee_id, today))
    already_checked = cur.fetchone()

    if already_checked:
        conn.close()
        return "<h1>Attendance already recorded for today.</h1><a href='/'>Go back</a>"

    # time check
    if current_time < start_time:
        conn.close()
        return f"<h1>Attendance opens at {ATTENDANCE_START}.</h1><a href='/'>Go back</a>"

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

    if current_time > end_time:
        status = "Absent"
    else:
        if is_within_allowed_area(employee_city, lat, lng):
            status = "Present"
        else:
            status = "Absent"

    cur.execute("""
        INSERT INTO attendance (employee_id, date, time, status, latitude, longitude, selfie_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        employee_id,
        today,
        now_time,
        status,
        latitude,
        longitude,
        filepath
    ))

    conn.commit()
    conn.close()

    return f"<h1>Attendance recorded for {employee_name}: {status}</h1><a href='/'>Go back</a>"


@app.route("/weekly_report")
def weekly_report():
    ensure_db_initialized()
    ensure_daily_absences()

    if not session.get("admin_logged_in"):
        return redirect(url_for("login"))

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=6)

    conn = sqlite3.connect("attendance.db")
    cur = conn.cursor()

    cur.execute("""
        SELECT employees.id,
               employees.name,
               employees.city,
               COUNT(attendance.id) as absent_days,
               GROUP_CONCAT(attendance.date, ', ') as absent_dates
        FROM employees
        LEFT JOIN attendance
            ON employees.id = attendance.employee_id
           AND attendance.status = 'Absent'
           AND attendance.date BETWEEN ? AND ?
        GROUP BY employees.id, employees.name, employees.city
        ORDER BY employees.city, employees.id
    """, (start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")))

    records = cur.fetchall()
    conn.close()

    return render_template(
        "weekly_report.html",
        records=records,
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d")
    )

@app.route("/monthly_report")
def monthly_report():
    ensure_db_initialized()
    ensure_daily_absences()

    if not session.get("admin_logged_in"):
        return redirect(url_for("login"))

    current_month = datetime.now().strftime("%Y-%m")

    conn = sqlite3.connect("attendance.db")
    cur = conn.cursor()

    cur.execute("""
        SELECT employees.id,
               employees.name,
               employees.city,
               COUNT(attendance.id) as absent_days,
               GROUP_CONCAT(attendance.date, ', ') as absent_dates
        FROM employees
        LEFT JOIN attendance
            ON employees.id = attendance.employee_id
           AND attendance.status = 'Absent'
           AND attendance.date LIKE ?
        GROUP BY employees.id, employees.name, employees.city
        ORDER BY employees.city, employees.id
    """, (f"{current_month}%",))

    records = cur.fetchall()
    conn.close()

    return render_template(
        "monthly_report.html",
        records=records,
        current_month=current_month
    )
@app.route("/clear_today_absent")
def clear_today_absent():
    ensure_db_initialized()

    if not session.get("admin_logged_in"):
        return redirect(url_for("login"))

    today = datetime.now().strftime("%Y-%m-%d")

    conn = sqlite3.connect("attendance.db")
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM attendance
        WHERE date = ? AND status = 'Absent'
    """, (today,))

    conn.commit()
    conn.close()

    return "<h1>Today's absent records were deleted.</h1><a href='/admin'>Back to Admin</a>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
