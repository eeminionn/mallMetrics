import sqlite3
import hashlib

from config import database_file


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def init_database():
    conn = sqlite3.connect(database_file)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
        )
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO usuarios (username, password_hash, role)
        VALUES (?, ?, ?)
    """, ("admin", hash_password("admin"), "admin"))

    conn.commit()
    conn.close()


def authenticate_user(username, password):
    conn = sqlite3.connect(database_file)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT username, password_hash, role
        FROM usuarios
        WHERE username = ?
    """, (username,))

    user = cursor.fetchone()
    conn.close()

    if user is None:
        return False, None

    stored_hash = user[1]
    role = user[2]

    if hash_password(password) == stored_hash:
        return True, role

    return False, None