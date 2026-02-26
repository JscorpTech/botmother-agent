"""Rich CLI interface for the Botmother flow agent."""

from __future__ import annotations

import sys

from langchain_core.messages import AIMessage, HumanMessage
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.theme import Theme

from botmother_agent.agent import AgentState, create_agent, save_flow

theme = Theme({
    "bot": "bold cyan",
    "user": "bold green",
    "info": "dim",
    "success": "bold green",
    "error": "bold red",
})

console = Console(theme=theme)


def _print_banner() -> None:
    console.print(Panel.fit(
        "[bold cyan]🤖 Botmother Flow Builder Agent[/]\n"
        "[dim]Telegram bot flow yaratuvchi AI agent[/]\n"
        "[dim]Chiqish uchun: quit | exit | Ctrl+C[/]",
        border_style="cyan",
    ))
    console.print()


def _print_ai_message(text: str) -> None:
    console.print()
    console.print(Markdown(text))
    console.print()


def main() -> None:
    """Main CLI entry point."""
    import os

    if not os.environ.get("OPENAI_API_KEY"):
        console.print("[error]❌ OPENAI_API_KEY environment variable not set![/]")
        console.print("[info]export OPENAI_API_KEY=sk-...[/]")
        sys.exit(1)

    _print_banner()

    agent = create_agent()
    state: dict = {
        "messages": [],
        "requirements": [],
        "flow_json": None,
        "phase": "chat",
        "turn_count": 0,
    }

    # Initial greeting
    console.print("[bot]Agent:[/] Salom! 👋 Men Botmother Flow Builder agentiman. "
                  "Telegram bot yaratishda yordam beraman.\n"
                  "Qanday bot yaratmoqchisiz? Menga aytib bering!\n")

    while True:
        try:
            user_input = console.input("[user]Siz:[/] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[info]Ko'rishguncha! 👋[/]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "chiqish", "выход"):
            console.print("[info]Ko'rishguncha! 👋[/]")
            break

        # Special commands
        if user_input.lower() in ("save", "saqlash", "сохранить"):
            if state.get("flow_json"):
                filepath = save_flow(state["flow_json"])
                console.print(f"[success]✅ Flow saqlandi: {filepath}[/]")
            else:
                console.print("[error]Hali flow yaratilmagan![/]")
            continue

        if user_input.lower() in ("show", "ko'rsat", "показать"):
            if state.get("flow_json"):
                console.print_json(state["flow_json"])
            else:
                console.print("[error]Hali flow yaratilmagan![/]")
            continue

        if user_input.lower() in ("reset", "qayta", "сброс"):
            state = {
                "messages": [],
                "requirements": [],
                "flow_json": None,
                "phase": "chat",
                "turn_count": 0,
            }
            console.print("[info]🔄 Suhbat qayta boshlandi![/]\n")
            continue

        # Run agent
        state["messages"] = list(state["messages"]) + [HumanMessage(content=user_input)]

        with console.status("[bot]Agent o'ylayapti...[/]", spinner="dots"):
            try:
                result = agent.invoke(state)
            except Exception as e:
                console.print(f"[error]❌ Xatolik: {e}[/]")
                continue

        # Update state
        state = {
            "messages": result["messages"],
            "requirements": result.get("requirements", state.get("requirements", [])),
            "flow_json": result.get("flow_json", state.get("flow_json")),
            "phase": result.get("phase", state.get("phase", "chat")),
            "turn_count": result.get("turn_count", state.get("turn_count", 0)),
        }

        # Print AI response
        last_ai_msgs = [m for m in result["messages"] if isinstance(m, AIMessage)]
        if last_ai_msgs:
            _print_ai_message(last_ai_msgs[-1].content)

        # If flow was generated, offer to save
        if state.get("flow_json") and state.get("phase") == "done":
            console.print("[success]✅ Flow JSON tayyor![/]")
            console.print("[info]Buyruqlar: save (saqlash) | show (ko'rish) | reset (qayta boshlash)[/]\n")


if __name__ == "__main__":
    main()
