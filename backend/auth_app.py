

import sqlite3
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash


# ============================================================
# APP CONFIGURATION
# ============================================================

app = Flask(__name__)

# Allow frontend (Next.js/React) to access Flask API
CORS(app)


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PARENT_DIR = BASE_DIR.parent
DB_PATH = (PARENT_DIR / "users.db") if (PARENT_DIR / "users.db").exists() else (BASE_DIR / "users.db")


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db_connection():

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    return conn


# ============================================================
# CREATE DATABASE
# ============================================================

def create_database():

    conn = get_db_connection()

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()

    conn.close()

    print(f"SQLite database ready: {DB_PATH}")


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/", methods=["GET"])
def home():

    return jsonify({
        "status": "success",
        "message": "ClaimCare Authentication API is running",
        "database": "SQLite",
        "port": 5000
    })


# ============================================================
# SIGN UP / REGISTER
# ============================================================

@app.route("/api/auth/signup", methods=["POST"])
def signup():

    try:

        # ----------------------------------------------------
        # Get request body
        # ----------------------------------------------------

        data = request.get_json(silent=True)

        if not data:

            return jsonify({
                "message": "Request body is required."
            }), 400


        # ----------------------------------------------------
        # Get email and password
        # ----------------------------------------------------

        email = data.get("email", "").strip().lower()
        password = data.get("password", "")


        # ----------------------------------------------------
        # Validate email
        # ----------------------------------------------------

        if not email:

            return jsonify({
                "message": "Email is required."
            }), 400


        # ----------------------------------------------------
        # Validate password
        # ----------------------------------------------------

        if not password:

            return jsonify({
                "message": "Password is required."
            }), 400


        if len(password) < 6:

            return jsonify({
                "message": "Password must be at least 6 characters."
            }), 400


        # ----------------------------------------------------
        # Connect to SQLite
        # ----------------------------------------------------

        conn = get_db_connection()


        # ----------------------------------------------------
        # Check whether user already exists
        # ----------------------------------------------------

        existing_user = conn.execute(
            """
            SELECT id
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()


        # ----------------------------------------------------
        # Email already registered
        # ----------------------------------------------------

        if existing_user is not None:

            conn.close()

            return jsonify({
                "message": "An account with this email already exists."
            }), 409


        # ----------------------------------------------------
        # Hash password
        # ----------------------------------------------------

        password_hash = generate_password_hash(password)


        # ----------------------------------------------------
        # Insert new user
        # ----------------------------------------------------

        cursor = conn.execute(
            """
            INSERT INTO users (
                email,
                password_hash
            )
            VALUES (?, ?)
            """,
            (
                email,
                password_hash
            )
        )


        user_id = cursor.lastrowid

        conn.commit()

        conn.close()


        # ----------------------------------------------------
        # Registration successful
        # ----------------------------------------------------

        return jsonify({

            "message": "Account created successfully.",

            "user": {
                "id": user_id,
                "email": email
            }

        }), 201


    except sqlite3.IntegrityError:

        return jsonify({
            "message": "An account with this email already exists."
        }), 409


    except Exception as e:

        print("========================================")
        print("SIGNUP ERROR")
        print("========================================")
        print(e)
        print("========================================")

        return jsonify({
            "message": "Internal server error."
        }), 500


# ============================================================
# LOGIN
# ============================================================

@app.route("/api/auth/login", methods=["POST"])
def login():

    try:

        # ----------------------------------------------------
        # Get request body
        # ----------------------------------------------------

        data = request.get_json(silent=True)

        if not data:

            return jsonify({
                "message": "Request body is required."
            }), 400


        # ----------------------------------------------------
        # Get email and password
        # ----------------------------------------------------

        email = data.get("email", "").strip().lower()
        password = data.get("password", "")


        # ----------------------------------------------------
        # Validate email
        # ----------------------------------------------------

        if not email:

            return jsonify({
                "message": "Email is required."
            }), 400


        # ----------------------------------------------------
        # Validate password
        # ----------------------------------------------------

        if not password:

            return jsonify({
                "message": "Password is required."
            }), 400


        # ----------------------------------------------------
        # Connect to SQLite
        # ----------------------------------------------------

        conn = get_db_connection()


        # ----------------------------------------------------
        # Find user by email
        # ----------------------------------------------------

        user = conn.execute(
            """
            SELECT
                id,
                email,
                password_hash
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()


        conn.close()


        # ----------------------------------------------------
        # User not found
        # ----------------------------------------------------

        if user is None:

            return jsonify({
                "message": "Invalid email or password."
            }), 401


        # ----------------------------------------------------
        # Verify password
        # ----------------------------------------------------

        password_correct = check_password_hash(
            user["password_hash"],
            password
        )


        # ----------------------------------------------------
        # Wrong password
        # ----------------------------------------------------

        if not password_correct:

            return jsonify({
                "message": "Invalid email or password."
            }), 401


        # ----------------------------------------------------
        # Login successful
        # ----------------------------------------------------

        return jsonify({

            "message": "Login successful.",

            "user": {
                "id": user["id"],
                "email": user["email"]
            }

        }), 200


    except Exception as e:

        print("========================================")
        print("LOGIN ERROR")
        print("========================================")
        print(e)
        print("========================================")

        return jsonify({
            "message": "Internal server error."
        }), 500


# ============================================================
# RUN SERVER
# ============================================================

if __name__ == "__main__":

    print("========================================")
    print("Starting ClaimCare Authentication API")
    print("========================================")

    # Create database/table
    create_database()

    print("")
    print("Available endpoints:")
    print("")
    print("SIGN UP:")
    print("POST http://localhost:5000/api/auth/signup")
    print("")
    print("LOGIN:")
    print("POST http://localhost:5000/api/auth/login")
    print("")
    print("========================================")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
