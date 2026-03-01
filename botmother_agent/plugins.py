"""Plugin API client + LangChain tools for SubFlow discovery.

Used by the agent to search for plugins and get their full schema
before creating or modifying SubFlowNode nodes.
"""

from __future__ import annotations

import json
import math
import os
import time

import httpx
from langchain_core.tools import tool

# ── API helpers ──────────────────────────────────────────────────────────

def _plugin_api_url() -> str:
    return os.environ.get("PLUGIN_API_URL", "").rstrip("/")


def _format_plugin_compact(p: dict) -> str:
    """Return a one-line summary of a plugin for prompt context."""
    slug = p.get("slug", "")
    name = p.get("name", "")
    desc = p.get("description", "")
    tags = p.get("tags") or []
    outputs = [o.get("name") for o in (p.get("outputs") or [])]
    params = list(((p.get("params_schema") or {}).get("properties") or {}).keys())
    line = f"slug:`{slug}` | {name}"
    if desc:
        line += f" — {desc}"
    if tags:
        line += f" | tags:{','.join(tags)}"
    if params:
        line += f" | params:{','.join(params)}"
    if outputs:
        line += f" | outputs:{','.join(outputs)}"
    return line


def _format_plugin_full(p: dict) -> str:
    """Return full plugin details as structured text for agent context."""
    lines = [
        f"Plugin: {p.get('name')} (slug: `{p.get('slug')}`)",
        f"Description: {p.get('description', '')}",
        f"Category: {p.get('category', '')}",
        f"Tags: {', '.join(p.get('tags') or [])}",
        f"Version: {p.get('version', '')}",
    ]

    outputs = p.get("outputs") or []
    if outputs:
        lines.append("Outputs (exit handles):")
        for o in outputs:
            lines.append(f"  - {o.get('name')}: {o.get('description', '')}")

    schema = p.get("params_schema") or {}
    props = schema.get("properties") or {}
    required = schema.get("required") or []
    if props:
        lines.append("Params schema:")
        for key, prop in props.items():
            req = " [required]" if key in required else ""
            ptype = prop.get("type", "any")
            desc = prop.get("description", "")
            default = prop.get("default")
            entry = f"  - {key} ({ptype}){req}"
            if desc:
                entry += f": {desc}"
            if default is not None:
                entry += f" (default: {json.dumps(default)})"
            lines.append(entry)

    lines.append(
        "\nSubFlowNode structure:\n"
        "{\n"
        f'  "type": "SubFlowNode",\n'
        f'  "data": {{\n'
        f'    "slug": "{p.get("slug")}",\n'
        f'    "pluginName": "{p.get("name")}",\n'
        f'    "pluginDescription": "{p.get("description", "")}",\n'
        f'    "params": {{ <fill from params schema> }},\n'
        f'    "paramsSchema": {json.dumps(schema)},\n'
        f'    "outputs": {json.dumps(outputs)}\n'
        f'  }}\n'
        "}"
    )
    return "\n".join(lines)


# ── LangChain Tools ──────────────────────────────────────────────────────

@tool
def search_plugins(query: str) -> str:
    """Search for SubFlow plugins by keyword (name, description, slug, tags).

    Use this BEFORE creating a SubFlowNode to find the correct slug.
    Returns a compact list of matching plugins.

    Args:
        query: keyword to search for (e.g. "form", "payment", "google sheets")
    """
    api = _plugin_api_url()
    if not api:
        return "Plugin API not configured."
    try:
        resp = httpx.get(
            f"{api}/subflows/search",
            params={"q": query, "active": "true", "per_page": 10},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            plugins = data.get("data", [])
            if not plugins:
                return f"No plugins found for query '{query}'."
            lines = [f"Found {len(plugins)} plugin(s) matching '{query}':"]
            for p in plugins:
                lines.append("  " + _format_plugin_compact(p))
            return "\n".join(lines)
        return f"Plugin search failed: HTTP {resp.status_code}"
    except Exception as e:
        return f"Plugin search error: {e}"


@tool
def get_plugin(slug: str) -> str:
    """Get full details of a SubFlow plugin by slug.

    Use this after search_plugins to get the exact params_schema and outputs
    needed to correctly populate a SubFlowNode.

    Args:
        slug: exact plugin slug (e.g. "google-form", "payment-bot")
    """
    api = _plugin_api_url()
    if not api:
        return "Plugin API not configured."
    try:
        resp = httpx.get(f"{api}/subflows/slug/{slug}", timeout=8)
        if resp.status_code == 200:
            return _format_plugin_full(resp.json())
        if resp.status_code == 404:
            return f"Plugin '{slug}' not found. Use search_plugins to find the correct slug."
        return f"Get plugin failed: HTTP {resp.status_code}"
    except Exception as e:
        return f"Get plugin error: {e}"


# List of all agent tools
PLUGIN_TOOLS = [search_plugins, get_plugin]
