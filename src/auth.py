from __future__ import annotations

import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import bcrypt

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
SESSION_TIMEOUT_MINUTES = 30

DEFAULT_ROLES = {
    "administrador": {"perfil": "full", "certificaciones": "full", "proyectos": "full", "datos_sensibles": "none"},
    "reclutador":    {"perfil": "full", "certificaciones": "full", "proyectos": "full", "datos_sensibles": "none"},
    "cliente":       {"perfil": "full", "certificaciones": "partial", "proyectos": "full", "datos_sensibles": "none"},
    "estudiante":    {"perfil": "full", "certificaciones": "partial", "proyectos": "partial", "datos_sensibles": "none"},
    "colega":        {"perfil": "full", "certificaciones": "partial", "proyectos": "partial", "datos_sensibles": "none"},
    "general":       {"perfil": "full", "certificaciones": "partial", "proyectos": "partial", "datos_sensibles": "none"},
}


@dataclass
class AuthResult:
    ok: bool
    message: str
    user_id: int | None = None
    role: str | None = None


class AuthManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                );

                CREATE TABLE IF NOT EXISTS permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_id INTEGER NOT NULL,
                    resource TEXT NOT NULL,
                    level TEXT NOT NULL CHECK(level IN ('none','partial','full')),
                    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
                    UNIQUE(role_id, resource)
                );

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role_id INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    locked_until TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (role_id) REFERENCES roles(id)
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    event_type TEXT NOT NULL,
                    detail TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
                """
            )
            self._seed_roles(conn)

    def _seed_roles(self, conn: sqlite3.Connection) -> None:
        for role_name, resources in DEFAULT_ROLES.items():
            conn.execute("INSERT OR IGNORE INTO roles (name) VALUES (?)", (role_name,))
            role_id = conn.execute(
                "SELECT id FROM roles WHERE name = ?", (role_name,)
            ).fetchone()["id"]
            for resource, level in resources.items():
                conn.execute(
                    "INSERT OR IGNORE INTO permissions (role_id, resource, level) VALUES (?, ?, ?)",
                    (role_id, resource, level),
                )

    def _insert_audit(self, conn: sqlite3.Connection, user_id: int | None, event_type: str, detail: str = "") -> None:
        """Inserta un evento de auditoría usando una conexión YA ABIERTA (no abre una nueva)."""
        conn.execute(
            "INSERT INTO audit_events (user_id, event_type, detail, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, event_type, detail, datetime.now().isoformat(timespec="seconds")),
        )

    def log_event(self, user_id: int | None, event_type: str, detail: str = "") -> None:
        """Registra un evento de auditoría abriendo su PROPIA conexión.
        Solo úsalo cuando no haya otra conexión ya abierta en el mismo hilo/llamada
        (por ejemplo, fuera de cualquier bloque `with self._connect() as conn:`)."""
        with self._connect() as conn:
            self._insert_audit(conn, user_id, event_type, detail)

    def create_user(self, username: str, password: str, role_name: str) -> AuthResult:
        if role_name not in DEFAULT_ROLES:
            return AuthResult(False, f"Rol inválido. Use uno de: {', '.join(DEFAULT_ROLES)}")

        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        with self._connect() as conn:
            role_row = conn.execute("SELECT id FROM roles WHERE name = ?", (role_name,)).fetchone()
            try:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role_id, active, created_at) VALUES (?, ?, ?, 1, ?)",
                    (username, password_hash, role_row["id"], datetime.now().isoformat(timespec="seconds")),
                )
            except sqlite3.IntegrityError:
                return AuthResult(False, "Ese nombre de usuario ya existe.")

        self.log_event(None, "user_created", f"username={username} role={role_name}")
        return AuthResult(True, "Usuario creado correctamente.")

    def authenticate(self, username: str, password: str) -> AuthResult:
        with self._connect() as conn:
            user = conn.execute(
                """
                SELECT users.*, roles.name AS role_name
                FROM users JOIN roles ON users.role_id = roles.id
                WHERE username = ?
                """,
                (username,),
            ).fetchone()

            if user is None:
                self._insert_audit(conn, None, "login_failed", f"username={username} reason=no_existe")
                return AuthResult(False, "Usuario o contraseña incorrectos.")

            if not user["active"]:
                self._insert_audit(conn, user["id"], "login_blocked", "usuario_desactivado")
                return AuthResult(False, "Este usuario está desactivado.")

            if user["locked_until"]:
                locked_until = datetime.fromisoformat(user["locked_until"])
                if datetime.now() < locked_until:
                    minutos = int((locked_until - datetime.now()).total_seconds() / 60) + 1
                    self._insert_audit(conn, user["id"], "login_blocked", "cuenta_bloqueada")
                    return AuthResult(False, f"Cuenta bloqueada. Intente de nuevo en {minutos} minuto(s).")

            valid = bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8"))

            if not valid:
                attempts = user["failed_attempts"] + 1
                locked_until = None
                if attempts >= MAX_FAILED_ATTEMPTS:
                    locked_until = (datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
                    attempts = 0

                conn.execute(
                    "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                    (attempts, locked_until, user["id"]),
                )
                self._insert_audit(conn, user["id"], "login_failed", f"intentos={attempts}")

                if locked_until:
                    return AuthResult(False, f"Demasiados intentos fallidos. Cuenta bloqueada por {LOCKOUT_MINUTES} minutos.")
                return AuthResult(False, "Usuario o contraseña incorrectos.")

            conn.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?",
                (user["id"],),
            )
            self._insert_audit(conn, user["id"], "login_success")
            return AuthResult(True, "Autenticación correcta.", user_id=user["id"], role=user["role_name"])

    def get_permissions(self, role_name: str) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT permissions.resource, permissions.level
                FROM permissions JOIN roles ON permissions.role_id = roles.id
                WHERE roles.name = ?
                """,
                (role_name,),
            ).fetchall()
        return {row["resource"]: row["level"] for row in rows}

    def deactivate_user(self, username: str) -> AuthResult:
        with self._connect() as conn:
            cur = conn.execute("UPDATE users SET active = 0 WHERE username = ?", (username,))
            if cur.rowcount == 0:
                return AuthResult(False, "Usuario no encontrado.")
        self.log_event(None, "user_revoked", f"username={username}")
        return AuthResult(True, "Usuario desactivado.")


class Session:
    def __init__(self, user_id: int, username: str, role: str):
        self.user_id = user_id
        self.username = username
        self.role = role
        self.last_activity = time.time()

    def touch(self) -> None:
        self.last_activity = time.time()

    def is_expired(self) -> bool:
        elapsed_minutes = (time.time() - self.last_activity) / 60
        return elapsed_minutes > SESSION_TIMEOUT_MINUTES


class SessionStore:
    """Guarda las sesiones activas en memoria (token -> Session)."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create(self, user_id: int, username: str, role: str) -> str:
        token = secrets.token_hex(32)
        self._sessions[token] = Session(user_id, username, role)
        return token

    def get(self, token: str) -> Session | None:
        session = self._sessions.get(token)
        if session is None:
            return None
        if session.is_expired():
            del self._sessions[token]
            return None
        session.touch()
        return session

    def destroy(self, token: str) -> None:
        self._sessions.pop(token, None)