"""FastAPI server for the Botmother flow agent.

Provides REST API with JWT auth, SQLite persistence, and session-based
conversational flow generation.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from botmother_agent.agent import create_agent, _extract_flow_json
from botmother_agent.auth import TokenPayload, get_current_user
from botmother_agent import database as db

# ── App ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Botmother Flow Agent API",
    description="Conversational AI agent that generates Telegram bot flow JSON for the Botmother engine",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    db.init_db()


# ── In-memory message cache (messages aren't serializable to DB easily) ──

_msg_cache: dict[str, list] = {}


# ── Request / Response Models ────────────────────────────────────────────

class CreateSessionResponse(BaseModel):
    session_id: str
    message: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    phase: str
    has_flow: bool
    flow_json: dict | None = None
    requirements: list[str] = []


class SessionInfo(BaseModel):
    session_id: str
    phase: str
    turn_count: int
    has_flow: bool
    requirements: list[str]
    created_at: str
    updated_at: str


class SessionListItem(BaseModel):
    session_id: str
    phase: str
    turn_count: int
    has_flow: bool
    created_at: str
    updated_at: str


class FlowOut(BaseModel):
    id: int
    name: str | None = None
    description: str | None = None
    flow_json: dict
    session_id: str | None = None
    created_at: str
    updated_at: str


class FlowListItem(BaseModel):
    id: int
    name: str | None = None
    description: str | None = None
    created_at: str
    updated_at: str


class SaveFlowRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class GenerateRequest(BaseModel):
    description: str = Field(..., min_length=10, max_length=10000)


class GenerateResponse(BaseModel):
    flow_json: dict
    reply: str
    flow_id: int | None = None


class UserProfile(BaseModel):
    id: str
    email: str | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    role: str
    created_at: str
    updated_at: str


class MessageItem(BaseModel):
    role: str
    content: str


# ── Helpers ──────────────────────────────────────────────────────────────

def _ensure_user(user: TokenPayload) -> None:
    """Upsert user from JWT claims into local DB."""
    db.upsert_user(
        user_id=str(user.user_id),
        email=user.email,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
    )


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _get_session_or_404(session_id: str, user_id: str) -> dict:
    session = db.get_session(session_id, str(user_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _serialize_messages(messages: list) -> list[dict]:
    result = []
    for m in messages:
        if isinstance(m, HumanMessage):
            result.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage):
            result.append({"role": "assistant", "content": m.content})
    return result


def _deserialize_messages(data: list[dict]) -> list:
    msgs = []
    for item in data:
        if item["role"] == "user":
            msgs.append(HumanMessage(content=item["content"]))
        elif item["role"] == "assistant":
            msgs.append(AIMessage(content=item["content"]))
    return msgs


def _load_messages(session_id: str, session_row: dict) -> list:
    """Load messages from cache or DB."""
    if session_id in _msg_cache:
        return _msg_cache[session_id]
    try:
        stored = json.loads(session_row.get("messages") or "[]")
        msgs = _deserialize_messages(stored)
    except (json.JSONDecodeError, TypeError):
        msgs = []
    _msg_cache[session_id] = msgs
    return msgs


def _save_messages(session_id: str, messages: list) -> None:
    """Persist messages to cache and DB."""
    _msg_cache[session_id] = messages
    serialized = json.dumps(_serialize_messages(messages), ensure_ascii=False)
    db.update_session(session_id, messages_json=serialized)


# ── Auth: /me ────────────────────────────────────────────────────────────

@app.get("/me", response_model=UserProfile, tags=["auth"])
def get_me(user: TokenPayload = Depends(get_current_user)):
    """Get current user profile."""
    _ensure_user(user)
    row = db.get_user(str(user.user_id))
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return UserProfile(id=row["id"], **{k: row[k] for k in ("email", "username", "first_name", "last_name", "role", "created_at", "updated_at")})


# ── Sessions ─────────────────────────────────────────────────────────────

@app.get("/sessions", response_model=list[SessionListItem], tags=["sessions"])
def list_sessions(user: TokenPayload = Depends(get_current_user)):
    """List all sessions for current user."""
    _ensure_user(user)
    rows = db.list_sessions(str(user.user_id))
    return [
        SessionListItem(
            session_id=r["id"],
            phase=r["phase"],
            turn_count=r["turn_count"],
            has_flow=bool(r["has_flow"]),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


@app.post("/sessions", response_model=CreateSessionResponse, tags=["sessions"])
def create_session(user: TokenPayload = Depends(get_current_user)):
    """Create a new conversation session."""
    _ensure_user(user)
    session_id = _uid()
    db.create_session(session_id, str(user.user_id))
    return CreateSessionResponse(
        session_id=session_id,
        message="Session created",
    )


@app.get("/sessions/{session_id}", response_model=SessionInfo, tags=["sessions"])
def get_session(session_id: str, user: TokenPayload = Depends(get_current_user)):
    """Get session info."""
    _ensure_user(user)
    s = _get_session_or_404(session_id, str(user.user_id))
    reqs = json.loads(s.get("requirements") or "[]")
    return SessionInfo(
        session_id=s["id"],
        phase=s["phase"],
        turn_count=s["turn_count"],
        has_flow=s["flow_json"] is not None,
        requirements=reqs,
        created_at=s["created_at"],
        updated_at=s["updated_at"],
    )


@app.delete("/sessions/{session_id}", tags=["sessions"])
def delete_session(session_id: str, user: TokenPayload = Depends(get_current_user)):
    """Delete a session."""
    _ensure_user(user)
    db.delete_session(session_id, str(user.user_id))
    _msg_cache.pop(session_id, None)
    return {"detail": "Session deleted"}


@app.post("/sessions/{session_id}/chat", response_model=ChatResponse, tags=["sessions"])
def chat(session_id: str, req: ChatRequest, user: TokenPayload = Depends(get_current_user)):
    """Send a message and get agent response."""
    _ensure_user(user)
    s = _get_session_or_404(session_id, str(user.user_id))

    messages = _load_messages(session_id, s)
    messages.append(HumanMessage(content=req.message))

    reqs = json.loads(s.get("requirements") or "[]")
    agent = create_agent()
    state = {
        "messages": messages,
        "requirements": reqs,
        "flow_json": s.get("flow_json"),
        "phase": s["phase"],
        "turn_count": s["turn_count"],
    }

    result = agent.invoke(state)

    new_messages = result["messages"]
    new_phase = result.get("phase", s["phase"])
    new_reqs = result.get("requirements", reqs)
    new_flow = result.get("flow_json", s.get("flow_json"))
    new_turn = result.get("turn_count", s["turn_count"])

    _save_messages(session_id, new_messages)
    db.update_session(
        session_id,
        phase=new_phase,
        turn_count=new_turn,
        requirements=new_reqs,
        flow_json=new_flow,
    )

    # Build response
    last_ai = ""
    for m in reversed(new_messages):
        if isinstance(m, AIMessage):
            last_ai = m.content
            break

    flow_dict = None
    if new_flow:
        try:
            flow_dict = json.loads(new_flow)
        except (json.JSONDecodeError, TypeError):
            pass

    return ChatResponse(
        session_id=session_id,
        reply=last_ai,
        phase=new_phase,
        has_flow=new_flow is not None,
        flow_json=flow_dict,
        requirements=new_reqs,
    )


@app.get("/sessions/{session_id}/flow", tags=["sessions"])
def get_session_flow(session_id: str, user: TokenPayload = Depends(get_current_user)):
    """Get the generated flow JSON for a session."""
    _ensure_user(user)
    s = _get_session_or_404(session_id, str(user.user_id))
    if not s.get("flow_json"):
        raise HTTPException(status_code=404, detail="No flow generated yet")
    return {"session_id": session_id, "flow_json": json.loads(s["flow_json"])}


@app.post("/sessions/{session_id}/flow/save", response_model=FlowOut, tags=["sessions"])
def save_session_flow(
    session_id: str,
    req: SaveFlowRequest = SaveFlowRequest(),
    user: TokenPayload = Depends(get_current_user),
):
    """Save the generated flow to database."""
    _ensure_user(user)
    s = _get_session_or_404(session_id, str(user.user_id))
    if not s.get("flow_json"):
        raise HTTPException(status_code=404, detail="No flow generated yet")

    record = db.save_flow_record(
        user_id=str(user.user_id),
        flow_json=s["flow_json"],
        name=req.name,
        description=req.description,
        session_id=session_id,
    )
    return FlowOut(
        id=record["id"],
        name=record["name"],
        description=record["description"],
        flow_json=json.loads(record["flow_json"]),
        session_id=record["session_id"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


@app.post("/sessions/{session_id}/reset", tags=["sessions"])
def reset_session(session_id: str, user: TokenPayload = Depends(get_current_user)):
    """Reset session conversation."""
    _ensure_user(user)
    _get_session_or_404(session_id, str(user.user_id))
    db.update_session(session_id, phase="chat", turn_count=0, requirements=[], flow_json=None, messages_json="[]")
    _msg_cache.pop(session_id, None)
    return {"detail": "Session reset"}


@app.get("/sessions/{session_id}/history", response_model=list[MessageItem], tags=["sessions"])
def get_history(session_id: str, user: TokenPayload = Depends(get_current_user)):
    """Get conversation history."""
    _ensure_user(user)
    s = _get_session_or_404(session_id, str(user.user_id))
    messages = _load_messages(session_id, s)
    items = _serialize_messages(messages)
    return [MessageItem(**m) for m in items]


# ── Flows (CRUD) ─────────────────────────────────────────────────────────

@app.get("/flows", response_model=list[FlowListItem], tags=["flows"])
def list_flows(user: TokenPayload = Depends(get_current_user)):
    """List all saved flows for current user."""
    _ensure_user(user)
    rows = db.list_flows(str(user.user_id))
    return [FlowListItem(**r) for r in rows]


@app.get("/flows/{flow_id}", response_model=FlowOut, tags=["flows"])
def get_flow(flow_id: int, user: TokenPayload = Depends(get_current_user)):
    """Get a saved flow by ID."""
    _ensure_user(user)
    row = db.get_flow(flow_id, str(user.user_id))
    if not row:
        raise HTTPException(status_code=404, detail="Flow not found")
    return FlowOut(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        flow_json=json.loads(row["flow_json"]),
        session_id=row["session_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@app.delete("/flows/{flow_id}", tags=["flows"])
def delete_flow(flow_id: int, user: TokenPayload = Depends(get_current_user)):
    """Delete a saved flow."""
    _ensure_user(user)
    if not db.delete_flow(flow_id, str(user.user_id)):
        raise HTTPException(status_code=404, detail="Flow not found")
    return {"detail": "Flow deleted"}


# ── One-shot generation ──────────────────────────────────────────────────

@app.post("/generate", response_model=GenerateResponse, tags=["generate"])
def generate_flow(
    req: GenerateRequest,
    save: bool = False,
    user: TokenPayload = Depends(get_current_user),
):
    """One-shot flow generation — describe your bot, get flow JSON."""
    _ensure_user(user)
    agent = create_agent()

    prompt = (
        f"Create a Telegram bot with these requirements:\n{req.description}\n\n"
        "Generate the complete flow JSON now."
    )

    state = {
        "messages": [HumanMessage(content=prompt)],
        "requirements": [],
        "flow_json": None,
        "phase": "generating",
        "turn_count": 0,
    }

    result = agent.invoke(state)

    flow_json_str = result.get("flow_json")
    if not flow_json_str:
        for m in reversed(result["messages"]):
            if isinstance(m, AIMessage):
                flow_json_str = _extract_flow_json(m.content)
                if flow_json_str:
                    break

    if not flow_json_str:
        raise HTTPException(status_code=422, detail="Could not generate a valid flow. Try providing more details.")

    flow_dict = json.loads(flow_json_str)

    last_reply = ""
    for m in reversed(result["messages"]):
        if isinstance(m, AIMessage):
            last_reply = m.content
            break

    flow_id = None
    if save:
        record = db.save_flow_record(user_id=str(user.user_id), flow_json=flow_json_str)
        flow_id = record["id"]

    return GenerateResponse(flow_json=flow_dict, reply=last_reply, flow_id=flow_id)


# ── Health ───────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}
