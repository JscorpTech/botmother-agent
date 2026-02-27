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
from botmother_agent.validator import format_errors, validate_flow

MAX_VALIDATION_RETRIES = 2


# ── State ────────────────────────────────────────────────────────────────

class AgentState(BaseModel):
    """The state of the agent throughout the conversation."""
    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    flow_json: str | None = None
    phase: str = "chat"  # chat | gathering | generating | validating | done
    turn_count: int = 0
    validation_retries: int = 0


# ── LLM Setup ────────────────────────────────────────────────────────────

def _get_llm() -> ChatOpenAI:
    model = os.environ.get("BOTMOTHER_MODEL", "gpt-4o")
    base_url = os.environ.get("OPENAI_API_BASE")
    kwargs: dict[str, Any] = {"model": model, "temperature": 0.3}
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


# ── Node functions ───────────────────────────────────────────────────────

def chat_node(state: AgentState) -> dict[str, Any]:
    """Main conversation node — talks with user, decides next step."""
    llm = _get_llm()

    sys_msg = SystemMessage(content=SYSTEM_PROMPT + "\n\n" + _phase_instructions(state))
    messages = [sys_msg] + list(state.messages)
    response = llm.invoke(messages)

    new_phase = _detect_phase(state, response.content)
    flow_json = _extract_flow_json(response.content)

    # Strip flow JSON from the visible message
    clean_content = _strip_flow_json(response.content) if flow_json else response.content
    clean_response = AIMessage(content=clean_content)

    updates: dict[str, Any] = {
        "messages": [clean_response],
        "turn_count": state.turn_count + 1,
    }

    if new_phase != state.phase:
        updates["phase"] = new_phase

    if flow_json:
        updates["flow_json"] = flow_json
        updates["phase"] = "validating"

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

    # Strip flow JSON from the visible message
    clean_content = _strip_flow_json(response.content) if flow_json else response.content
    clean_response = AIMessage(content=clean_content)

    updates: dict[str, Any] = {"messages": [clean_response]}
    if flow_json:
        updates["flow_json"] = flow_json
        updates["phase"] = "validating"
    else:
        updates["phase"] = "chat"

    return updates


def validate_flow_node(state: AgentState) -> dict[str, Any]:
    """Validate the generated flow JSON. If invalid, ask AI to fix it."""
    if not state.flow_json:
        return {"phase": "chat"}

    errors = validate_flow(state.flow_json)

    if not errors:
        return {"phase": "done"}

    # Max retries reached — accept as-is
    if state.validation_retries >= MAX_VALIDATION_RETRIES:
        return {"phase": "done"}

    # Ask AI to fix the errors
    llm = _get_llm()
    fix_prompt = (
        f"The generated flow JSON has the following validation errors:\n"
        f"{format_errors(errors)}\n\n"
        f"Here is the current flow JSON:\n```json\n{state.flow_json}\n```\n\n"
        f"Fix ALL these errors and regenerate the complete flow JSON. "
        f"Output ONLY the corrected JSON inside ```json ... ``` markers."
    )

    sys_msg = SystemMessage(content=SYSTEM_PROMPT)
    messages = [sys_msg] + list(state.messages) + [HumanMessage(content=fix_prompt)]
    response = llm.invoke(messages)

    fixed_flow = _extract_flow_json(response.content)
    updates: dict[str, Any] = {"validation_retries": state.validation_retries + 1}

    if fixed_flow:
        updates["flow_json"] = fixed_flow
        # Re-validate (will loop back)
        updates["phase"] = "validating"
    else:
        # Couldn't extract fixed JSON — accept what we have
        updates["phase"] = "done"

    return updates


# ── Routing ──────────────────────────────────────────────────────────────

def route_after_chat(state: AgentState) -> Literal["generate_flow", "validate_flow", "end"]:
    if state.phase == "generating":
        return "generate_flow"
    if state.phase == "validating":
        return "validate_flow"
    return "end"


def route_after_generate(state: AgentState) -> Literal["validate_flow", "end"]:
    if state.phase == "validating":
        return "validate_flow"
    return "end"


def route_after_validate(state: AgentState) -> Literal["validate_flow", "end"]:
    if state.phase == "validating":
        return "validate_flow"
    return "end"


# ── Helpers ──────────────────────────────────────────────────────────────

def _phase_instructions(state: AgentState) -> str:
    """Add phase-specific instructions to the system prompt."""
    if state.phase == "chat":
        return (
            "\n## Current Phase: CHAT\n"
            "You're chatting with the user. If they mention creating a bot or describe any bot functionality, "
            "generate the flow JSON immediately using what they told you. Fill in sensible defaults. "
            "Do NOT ask clarifying questions unless the request is completely unclear."
        )
    elif state.phase == "gathering":
        reqs = "\n".join(f"- {r}" for r in state.requirements) if state.requirements else "None yet"
        return (
            f"\n## Current Phase: GATHERING REQUIREMENTS\n"
            f"Requirements collected so far:\n{reqs}\n\n"
            "You have enough context. Generate the flow JSON now. "
            "Use sensible defaults for anything not explicitly mentioned."
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

    if state.phase == "chat":
        if any(k in lower for k in bot_keywords):
            return "generating"
    elif state.phase == "gathering":
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


def _strip_flow_json(text: str) -> str:
    """Remove flow JSON code blocks from message text so the user never sees raw JSON."""
    pattern = r"```json\s*[\s\S]*?\s*```"
    cleaned = re.sub(pattern, "", text).strip()
    # Clean up leftover empty lines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned if cleaned else "Flow tayyor! 🎉"


# ── Graph Builder ────────────────────────────────────────────────────────

def create_agent() -> StateGraph:
    """Create the LangGraph agent."""
    graph = StateGraph(AgentState)

    graph.add_node("chat", chat_node)
    graph.add_node("generate_flow", generate_flow_node)
    graph.add_node("validate_flow", validate_flow_node)

    graph.set_entry_point("chat")

    graph.add_conditional_edges("chat", route_after_chat, {
        "generate_flow": "generate_flow",
        "validate_flow": "validate_flow",
        "end": END,
    })
    graph.add_conditional_edges("generate_flow", route_after_generate, {
        "validate_flow": "validate_flow",
        "end": END,
    })
    graph.add_conditional_edges("validate_flow", route_after_validate, {
        "validate_flow": "validate_flow",
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
