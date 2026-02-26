"""LangGraph agent for Botmother flow generation."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from botmother_agent.prompts import FLOW_GENERATION_PROMPT, SYSTEM_PROMPT


# ── State ────────────────────────────────────────────────────────────────

class AgentState(BaseModel):
    """The state of the agent throughout the conversation."""
    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    flow_json: str | None = None
    phase: str = "chat"  # chat | gathering | generating | done
    turn_count: int = 0


# ── LLM Setup ────────────────────────────────────────────────────────────

def _get_llm() -> ChatOpenAI:
    model = os.environ.get("BOTMOTHER_MODEL", "gpt-4o")
    return ChatOpenAI(model=model, temperature=0.3)


# ── Node functions ───────────────────────────────────────────────────────

def chat_node(state: AgentState) -> dict[str, Any]:
    """Main conversation node — talks with user, decides next step."""
    llm = _get_llm()

    sys_msg = SystemMessage(content=SYSTEM_PROMPT + "\n\n" + _phase_instructions(state))
    messages = [sys_msg] + list(state.messages)
    response = llm.invoke(messages)

    new_phase = _detect_phase(state, response.content)
    flow_json = _extract_flow_json(response.content)

    updates: dict[str, Any] = {
        "messages": [response],
        "turn_count": state.turn_count + 1,
    }

    if new_phase != state.phase:
        updates["phase"] = new_phase

    if flow_json:
        updates["flow_json"] = flow_json
        updates["phase"] = "done"

    # Extract requirements from conversation
    reqs = _extract_requirements(response.content, state.requirements)
    if reqs != state.requirements:
        updates["requirements"] = reqs

    return updates


def generate_flow_node(state: AgentState) -> dict[str, Any]:
    """Dedicated flow generation node — called when enough info is gathered."""
    llm = _get_llm()

    req_text = "\n".join(f"- {r}" for r in state.requirements) if state.requirements else "See conversation above."

    sys_msg = SystemMessage(content=SYSTEM_PROMPT)
    gen_msg = HumanMessage(content=FLOW_GENERATION_PROMPT.format(requirements=req_text))

    messages = [sys_msg] + list(state.messages) + [gen_msg]
    response = llm.invoke(messages)

    flow_json = _extract_flow_json(response.content)

    updates: dict[str, Any] = {"messages": [response]}
    if flow_json:
        updates["flow_json"] = flow_json
        updates["phase"] = "done"
    else:
        updates["phase"] = "chat"

    return updates


# ── Routing ──────────────────────────────────────────────────────────────

def route_after_chat(state: AgentState) -> Literal["generate_flow", "end"]:
    if state.phase == "generating":
        return "generate_flow"
    return "end"


def route_after_generate(state: AgentState) -> Literal["end"]:
    return "end"


# ── Helpers ──────────────────────────────────────────────────────────────

def _phase_instructions(state: AgentState) -> str:
    """Add phase-specific instructions to the system prompt."""
    if state.phase == "chat":
        return (
            "\n## Current Phase: CHAT\n"
            "You're having a general conversation. If the user mentions creating a bot, "
            "switch to gathering requirements. Ask 1-2 clarifying questions at a time.\n"
            "If you already have enough information to build the flow, generate the JSON directly."
        )
    elif state.phase == "gathering":
        reqs = "\n".join(f"- {r}" for r in state.requirements) if state.requirements else "None yet"
        return (
            f"\n## Current Phase: GATHERING REQUIREMENTS\n"
            f"Requirements collected so far:\n{reqs}\n\n"
            "Continue asking clarifying questions. When you have enough, generate the flow JSON.\n"
            "Ask about: commands, button interactions, data to collect, conditions, database needs."
        )
    elif state.phase == "generating":
        return "\n## Current Phase: GENERATING\nGenerate the flow JSON now."
    return ""


def _detect_phase(state: AgentState, response_text: str) -> str:
    """Detect what phase we should be in based on the response."""
    if _extract_flow_json(response_text):
        return "done"

    lower = response_text.lower()
    bot_keywords = ["bot", "бот", "flow", "флоу", "yaratish", "создать", "create"]
    question_markers = ["?", "qanday", "какой", "nechta", "сколько", "what", "which", "how many"]

    if state.phase == "chat":
        if any(k in lower for k in bot_keywords) and any(q in lower for q in question_markers):
            return "gathering"
    elif state.phase == "gathering":
        if state.turn_count > 6:
            return "generating"

    return state.phase


def _extract_requirements(response_text: str, existing: list[str]) -> list[str]:
    """Extract stated requirements from AI responses."""
    # Look for bullet points that summarize requirements
    lines = response_text.split("\n")
    reqs = list(existing)
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("- ", "• ", "* ", "✅ ")) and len(stripped) > 10:
            req = stripped.lstrip("-•* ✅").strip()
            if req not in reqs and len(req) < 200:
                reqs.append(req)
    return reqs


def _extract_flow_json(text: str) -> str | None:
    """Extract JSON from markdown code blocks."""
    pattern = r"```json\s*([\s\S]*?)\s*```"
    matches = re.findall(pattern, text)
    for match in matches:
        try:
            parsed = json.loads(match)
            if "nodes" in parsed and "edges" in parsed:
                return json.dumps(parsed, indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            continue
    return None


# ── Graph Builder ────────────────────────────────────────────────────────

def create_agent() -> StateGraph:
    """Create the LangGraph agent."""
    graph = StateGraph(AgentState)

    graph.add_node("chat", chat_node)
    graph.add_node("generate_flow", generate_flow_node)

    graph.set_entry_point("chat")

    graph.add_conditional_edges("chat", route_after_chat, {
        "generate_flow": "generate_flow",
        "end": END,
    })
    graph.add_conditional_edges("generate_flow", route_after_generate, {
        "end": END,
    })

    return graph.compile()


def save_flow(flow_json: str, filename: str | None = None) -> str:
    """Save generated flow JSON to flows/ directory."""
    flows_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "flows")
    os.makedirs(flows_dir, exist_ok=True)

    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"flow_{timestamp}.json"

    filepath = os.path.join(flows_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(flow_json)

    return filepath


def run_agent(user_message: str, state: AgentState | None = None) -> AgentState:
    """Run the agent with a single user message and return updated state."""
    agent = create_agent()

    if state is None:
        state = AgentState()

    input_state = {
        "messages": state.messages + [HumanMessage(content=user_message)],
        "requirements": state.requirements,
        "flow_json": state.flow_json,
        "phase": state.phase,
        "turn_count": state.turn_count,
    }

    result = agent.invoke(input_state)

    return AgentState(
        messages=result["messages"],
        requirements=result.get("requirements", state.requirements),
        flow_json=result.get("flow_json", state.flow_json),
        phase=result.get("phase", state.phase),
        turn_count=result.get("turn_count", state.turn_count),
    )
