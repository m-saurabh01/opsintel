import hashlib
import hmac
import secrets
import sqlite3
import time

from opsintel.db import transaction

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 1024
SESSION_TOKEN_BYTES = 32


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = encoded.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def validate_credentials(username: str, password: str) -> tuple[str, str]:
    username = username.strip()
    if not 3 <= len(username) <= 64 or any(ord(char) < 33 for char in username):
        raise ValueError("username must be 3 to 64 visible characters")
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise ValueError(f"password must be {PASSWORD_MIN_LENGTH} to {PASSWORD_MAX_LENGTH} characters")
    return username, _password_hash(password)


def create_user(conn: sqlite3.Connection, username: str, password: str, role: str) -> dict:
    if role not in {"admin", "user"}:
        raise ValueError("invalid role")
    username, password_hash = validate_credentials(username, password)
    try:
        cursor = conn.execute(
            "INSERT INTO users(username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("username is already registered") from exc
    return {"id": cursor.lastrowid, "username": username, "role": role}


def create_session(conn: sqlite3.Connection, user_id: int, ttl_s: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    csrf_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    now = time.time()
    conn.execute(
        "INSERT INTO auth_sessions(token_hash, csrf_hash, user_id, created_at, expires_at, last_seen_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (hashlib.sha256(token.encode()).hexdigest(), hashlib.sha256(csrf_token.encode()).hexdigest(),
         user_id, now, now + ttl_s, now),
    )
    return token, csrf_token


def authenticate(conn: sqlite3.Connection, token: str | None) -> tuple[dict, str] | None:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = conn.execute(
        "SELECT u.id, u.username, u.role, u.ai_enabled, u.ai_daily_limit, s.csrf_hash, s.expires_at "
        "FROM auth_sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND u.enabled = 1",
        (token_hash,),
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] <= time.time():
        conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"],
            "ai_enabled": bool(row["ai_enabled"]), "ai_daily_limit": row["ai_daily_limit"]}, row["csrf_hash"]


def verify_csrf(csrf_hash: str, token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), csrf_hash)


def revoke_session(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))


def login_is_limited(conn: sqlite3.Connection, username: str, now: float | None = None) -> bool:
    now = now or time.time()
    conn.execute("DELETE FROM auth_login_attempts WHERE attempted_at < ?", (now - 86400,))
    row = conn.execute(
        "SELECT count(*) FROM auth_login_attempts WHERE username_key = ? AND attempted_at >= ?",
        (username.strip().casefold(), now - 900),
    ).fetchone()
    return row[0] >= 5


def record_login_failure(conn: sqlite3.Connection, username: str, now: float | None = None) -> None:
    conn.execute("INSERT INTO auth_login_attempts(username_key, attempted_at) VALUES (?, ?)",
                 (username.strip().casefold(), now or time.time()))


def record_login_success(conn: sqlite3.Connection, user_id: int, username: str) -> None:
    with transaction(conn):
        conn.execute("UPDATE users SET last_login_at = datetime('now') WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM auth_login_attempts WHERE username_key = ?", (username.casefold(),))
