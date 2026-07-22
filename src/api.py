from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import AppConfig
from .rag import PersonalRAG
from . import roles as roles_module
from .auth import AuthManager, SessionStore, DEFAULT_ROLES

app = FastAPI(title="Personal RAG API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

config = AppConfig()
rag = PersonalRAG(config)

# Reutiliza tu AuthManager real (storage/auth.db) y un almacén de sesiones en memoria
auth_manager = AuthManager(Path("storage/auth.db"))
sessions = SessionStore()

ROLES = None
for attr_name in ("ROLES", "roles", "ROLE_MAP", "PROFILES"):
    if hasattr(roles_module, attr_name):
        ROLES = getattr(roles_module, attr_name)
        break

if ROLES is None:
    raise ImportError(
        "No se encontro un diccionario de roles en src/roles.py. "
        "Contenido disponible: " + ", ".join(dir(roles_module))
    )


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    role: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str = "general"


class RegisterResponse(BaseModel):
    ok: bool
    message: str


class ChatRequest(BaseModel):
    question: str
    role: str = "publico"


class Source(BaseModel):
    score: float | None = None
    file_name: str
    document_type: str
    text: str


class ChatResponse(BaseModel):
    answer: str
    language: str
    sources: list[Source] = []


def get_current_user(authorization: Optional[str] = Header(None)):
    """Dependencia que exige un header 'Authorization: Bearer <token>' con sesión válida."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No autenticado.")
    token = authorization.removeprefix("Bearer ").strip()
    session = sessions.get(token)
    if session is None:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada.")
    return session


@app.get("/account-roles")
def get_account_roles():
    """Roles disponibles al crear una cuenta nueva (distinto de los roles del chat)."""
    return {"roles": list(DEFAULT_ROLES.keys())}


@app.post("/register", response_model=RegisterResponse)
def register(payload: RegisterRequest):
    username = payload.username.strip()
    password = payload.password

    if len(username) < 3:
        raise HTTPException(status_code=400, detail="El usuario debe tener al menos 3 caracteres.")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 6 caracteres.")

    result = auth_manager.create_user(username, password, payload.role)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.message)
    return RegisterResponse(ok=True, message=result.message)


@app.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    result = auth_manager.authenticate(payload.username, payload.password)
    if not result.ok:
        raise HTTPException(status_code=401, detail=result.message)
    token = sessions.create(result.user_id, payload.username, result.role)
    return LoginResponse(token=token, username=payload.username, role=result.role)


@app.post("/logout")
def logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        sessions.destroy(authorization.removeprefix("Bearer ").strip())
    return {"ok": True}


@app.get("/roles")
def get_roles(user=Depends(get_current_user)):
    return {"roles": list(ROLES.keys())}


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, user=Depends(get_current_user)):
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacia.")

    role = ROLES.get(payload.role)
    if role is None:
        raise HTTPException(
            status_code=400,
            detail=f"Rol invalido: {payload.role}. Roles disponibles: {list(ROLES.keys())}",
        )

    try:
        result = rag.ask(question, role)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return ChatResponse(
        answer=result["answer"],
        language=result["language"],
        sources=result.get("sources", []),
    )


# IMPORTANTE: esto va SIEMPRE al final, después de todas las rutas de arriba
app.mount("/", StaticFiles(directory="static", html=True), name="static")