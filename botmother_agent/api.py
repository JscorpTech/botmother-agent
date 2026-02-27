"""FastAPI server for the Botmother flow agent.

Provides REST API for conversational flow generation with session management.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from botmother_agent.agent import AgentState, create_agent, save_flow, _extract_flow_json

# ── App ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Botmother Flow Agent API",
    description="Conversational AI agent that generates Telegram bot flow JSON for the Botmother engine",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory session store ──────────────────────────────────────────────

_sessions: dict[str, SessionData] = {}
_SESSION_TTL = timedelta(hours=2)


class SessionData:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {
            "messages": [],
            "requirements": [],
            "flow_json": None,
            "phase": "chat",
            "turn_count": 0,
        }
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    @property
    def expired(self) -> bool:
        return datetime.utcnow() - self.updated_at > _SESSION_TTL

    def touch(self) -> None:
        self.updated_at = datetime.utcnow()


def _get_session(session_id: str) -> SessionData:
    session = _sessions.get(session_id)
    if not session or session.expired:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    session.touch()
    return session


def _cleanup_expired() -> None:
    expired = [k for k, v in _sessions.items() if v.expired]
    for k in expired:
        del _sessions[k]


# ── Request/Response Models ──────────────────────────────────────────────

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


class FlowResponse(BaseModel):
    session_id: str
    flow_json: dict
    saved_path: str | None = None


class SessionInfo(BaseModel):
    session_id: str
    phase: str
    turn_count: int
    has_flow: bool
    requirements: list[str]
    created_at: str
    updated_at: str


# ── Helpers ──────────────────────────────────────────────────────────────

def _serialize_messages(messages: list) -> list[dict]:
    result = []
    for m in messages:
        if isinstance(m, HumanMessage):
            result.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage):
            result.append({"role": "assistant", "content": m.content})
    return result


def _state_to_response(session_id: str, state: dict) -> ChatResponse:
    last_ai = None
    for m in reversed(state["messages"]):
        if isinstance(m, AIMessage):
            last_ai = m.content
            break

    flow_dict = None
    if state.get("flow_json"):
        try:
            flow_dict = json.loads(state["flow_json"])
        except (json.JSONDecodeError, TypeError):
            pass

    return ChatResponse(
        session_id=session_id,
        reply=last_ai or "",
        phase=state.get("phase", "chat"),
        has_flow=state.get("flow_json") is not None,
        flow_json=flow_dict,
        requirements=state.get("requirements", []),
    )


# ── Endpoints ────────────────────────────────────────────────────────────

@app.post("/sessions", response_model=CreateSessionResponse)
def create_session():
    """Create a new conversation session."""
    _cleanup_expired()
    session_id = uuid.uuid4().hex[:12]
    _sessions[session_id] = SessionData()
    return CreateSessionResponse(
        session_id=session_id,
        message="Session created. Send messages via POST /sessions/{session_id}/chat",
    )


@app.get("/sessions/{session_id}", response_model=SessionInfo)
def get_session(session_id: str):
    """Get session info and status."""
    session = _get_session(session_id)
    return SessionInfo(
        session_id=session_id,
        phase=session.state.get("phase", "chat"),
        turn_count=session.state.get("turn_count", 0),
        has_flow=session.state.get("flow_json") is not None,
        requirements=session.state.get("requirements", []),
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    """Delete a session."""
    if session_id in _sessions:
        del _sessions[session_id]
    return {"detail": "Session deleted"}


@app.post("/sessions/{session_id}/chat", response_model=ChatResponse)
def chat(session_id: str, req: ChatRequest):
    """Send a message and get agent response."""
    session = _get_session(session_id)
    agent = create_agent()

    session.state["messages"] = list(session.state["messages"]) + [
        HumanMessage(content=req.message)
    ]

    result = agent.invoke(session.state)

    session.state = {
        "messages": result["messages"],
        "requirements": result.get("requirements", session.state.get("requirements", [])),
        "flow_json": result.get("flow_json", session.state.get("flow_json")),
        "phase": result.get("phase", session.state.get("phase", "chat")),
        "turn_count": result.get("turn_count", session.state.get("turn_count", 0)),
    }

    return _state_to_response(session_id, session.state)


@app.get("/sessions/{session_id}/flow", response_model=FlowResponse)
def get_flow(session_id: str):
    """Get the generated flow JSON for a session."""
    session = _get_session(session_id)
    if not session.state.get("flow_json"):
        raise HTTPException(status_code=404, detail="No flow generated yet")

    flow_dict = json.loads(session.state["flow_json"])
    return FlowResponse(session_id=session_id, flow_json=flow_dict)


@app.post("/sessions/{session_id}/flow/save", response_model=FlowResponse)
def save_session_flow(session_id: str, filename: str | None = None):
    """Save the generated flow to a file."""
    session = _get_session(session_id)
    if not session.state.get("flow_json"):
        raise HTTPException(status_code=404, detail="No flow generated yet")

    path = save_flow(session.state["flow_json"], filename)
    flow_dict = json.loads(session.state["flow_json"])
    return FlowResponse(session_id=session_id, flow_json=flow_dict, saved_path=path)


@app.post("/sessions/{session_id}/reset")
def reset_session(session_id: str):
    """Reset session conversation, keep session alive."""
    session = _get_session(session_id)
    session.state = {
        "messages": [],
        "requirements": [],
        "flow_json": None,
        "phase": "chat",
        "turn_count": 0,
    }
    return {"detail": "Session reset"}


@app.get("/sessions/{session_id}/history")
def get_history(session_id: str):
    """Get conversation history."""
    session = _get_session(session_id)
    return {"session_id": session_id, "messages": _serialize_messages(session.state["messages"])}


# ── One-shot endpoint (no session needed) ────────────────────────────────

class GenerateRequest(BaseModel):
    description: str = Field(..., min_length=10, max_length=10000,
                             description="Bot description / requirements")


class GenerateResponse(BaseModel):
    flow_json: dict
    reply: str
    saved_path: str | None = None


@app.post("/generate", response_model=GenerateResponse)
def generate_flow(req: GenerateRequest, save: bool = False):
    """One-shot flow generation — describe your bot and get flow JSON directly."""
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
        # Try extracting from the last AI message
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

    saved_path = None
    if save:
        saved_path = save_flow(flow_json_str)

    return GenerateResponse(flow_json=flow_dict, reply=last_reply, saved_path=saved_path)


@app.get("/health")
def health():
    return {"status": "ok", "active_sessions": len(_sessions)}
