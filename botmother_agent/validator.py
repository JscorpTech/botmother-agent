"""Validates generated flow JSON against Botmother engine rules."""

from __future__ import annotations

import json
from typing import Any


# All known node types
TRIGGER_TYPES = {
    "CommandTriggerNode",
    "MessageTriggerNode",
    "CallbackQueryTriggerNode",
    "CallbackButtonTriggerNode",
    "ReplyButtonTriggerNode",
    "CronTriggerNode",
}

ALL_NODE_TYPES = TRIGGER_TYPES | {
    # Messages
    "SendTextMessageNode", "SendPhotoNode", "SendVideoNode", "SendAudioNode",
    "SendFileNode", "SendAnimationNode", "SendVoiceNode", "SendVideoNoteNode",
    "SendLocationNode", "SendContactNode", "SendPollNode", "SendStickerNode",
    "SendMediaGroupNode", "SendVenueNode", "SendDiceNode",
    # Message ops
    "EditMessageNode", "DeleteMessageNode", "ForwardMessageNode",
    "CopyMessageNode", "PinMessageNode", "UnpinMessageNode", "UnpinAllMessagesNode",
    # Interactive
    "ChatActionNode", "CallbackQueryAnswerNode", "CheckMembershipNode",
    # Flow control
    "IfConditionNode", "RandomNode", "ForLoopNode", "ForLoopContinueNode", "PauseNode",
    # Data
    "VariableNode", "StateNode", "CollectionNode",
    "LoadCollectionItemNode", "LoadCollectionListNode",
    "UpdateCollectionNode", "DeleteCollectionNode",
    # Integration
    "HTTPRequestNode", "CustomCodeNode", "SendToAdminNode", "DelayNode",
}

# Required data fields per node type
REQUIRED_FIELDS: dict[str, list[str]] = {
    "CommandTriggerNode": ["command"],
    "SendTextMessageNode": ["messageText"],
    "SendPhotoNode": ["photo"],
    "SendVideoNode": ["video"],
    "SendAudioNode": ["audio"],
    "SendFileNode": ["document"],
    "SendLocationNode": ["latitude", "longitude"],
    "SendContactNode": ["phoneNumber", "firstName"],
    "HTTPRequestNode": ["method", "url"],
    "CustomCodeNode": ["jsCode"],
    "VariableNode": ["variableName", "operation"],
    "StateNode": ["key"],
    "CollectionNode": ["collection_name"],
    "LoadCollectionItemNode": ["collection", "contextKey"],
    "LoadCollectionListNode": ["collection", "contextKey"],
    "DelayNode": ["delay"],
    "CheckMembershipNode": ["channelId"],
    "CronTriggerNode": ["schedule"],
    "ForLoopNode": ["loopMode"],
    "SendToAdminNode": ["adminChatId", "messageText"],
}

# Conditional nodes that require specific sourceHandles on edges
CONDITIONAL_HANDLES: dict[str, set[str]] = {
    "IfConditionNode": {"true", "false", "branch_0", "branch_1", "branch_2", "branch_3"},
    "ForLoopNode": {"loop-body", "no-items"},
    "ForLoopContinueNode": {"loop-continue", "loop-done"},
    "LoadCollectionItemNode": {"found", "not_found"},
    "CheckMembershipNode": {"is-member", "not-member"},
    "RandomNode": {f"option_{i}" for i in range(10)},
}


def validate_flow(flow_json: str) -> list[str]:
    """Validate a flow JSON and return a list of error messages. Empty list = valid."""
    errors: list[str] = []

    try:
        flow = json.loads(flow_json)
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]

    if not isinstance(flow, dict):
        return ["Flow must be a JSON object"]

    nodes = flow.get("nodes")
    edges = flow.get("edges")

    if not isinstance(nodes, list):
        errors.append("Missing or invalid 'nodes' array")
        return errors
    if not isinstance(edges, list):
        errors.append("Missing or invalid 'edges' array")
        return errors

    if not nodes:
        errors.append("Flow has no nodes")
        return errors

    # Collect node info
    node_ids: set[str] = set()
    node_types: dict[str, str] = {}
    has_trigger = False

    for i, node in enumerate(nodes):
        nid = node.get("id")
        ntype = node.get("type")
        data = node.get("data", {})

        if not nid:
            errors.append(f"Node at index {i} has no 'id'")
            continue
        if not ntype:
            errors.append(f"Node '{nid}' has no 'type'")
            continue

        # Duplicate ID
        if nid in node_ids:
            errors.append(f"Duplicate node ID: '{nid}'")
        node_ids.add(nid)
        node_types[nid] = ntype

        # Unknown type
        if ntype not in ALL_NODE_TYPES:
            errors.append(f"Node '{nid}': unknown type '{ntype}'")

        # Trigger check
        if ntype in TRIGGER_TYPES:
            has_trigger = True

        # Required fields
        if ntype in REQUIRED_FIELDS and isinstance(data, dict):
            for field in REQUIRED_FIELDS[ntype]:
                if field not in data or data[field] is None or data[field] == "":
                    errors.append(f"Node '{nid}' ({ntype}): missing required field '{field}'")

        # Position check
        if "position" not in node:
            errors.append(f"Node '{nid}': missing 'position'")

    if not has_trigger:
        errors.append("Flow must have at least one trigger node (CommandTriggerNode, MessageTriggerNode, etc.)")

    # Validate edges
    edge_ids: set[str] = set()
    outgoing: dict[str, list[str]] = {}

    for i, edge in enumerate(edges):
        eid = edge.get("id")
        source = edge.get("source")
        target = edge.get("target")
        handle = edge.get("sourceHandle")

        if not source or not target:
            errors.append(f"Edge at index {i}: missing 'source' or 'target'")
            continue

        if eid:
            if eid in edge_ids:
                errors.append(f"Duplicate edge ID: '{eid}'")
            edge_ids.add(eid)

        # References to non-existent nodes
        if source not in node_ids:
            errors.append(f"Edge '{eid or i}': source '{source}' does not exist")
        if target not in node_ids:
            errors.append(f"Edge '{eid or i}': target '{target}' does not exist")

        # Track outgoing edges
        if source in node_ids:
            outgoing.setdefault(source, []).append(handle)

        # Validate sourceHandle for conditional nodes
        if source in node_types and handle:
            src_type = node_types[source]
            if src_type in CONDITIONAL_HANDLES:
                valid = CONDITIONAL_HANDLES[src_type]
                if handle not in valid:
                    errors.append(
                        f"Edge '{eid or i}': invalid sourceHandle '{handle}' "
                        f"for {src_type} (valid: {sorted(valid)})"
                    )

    # Conditional nodes must have outgoing edges with handles
    for nid, ntype in node_types.items():
        if ntype in CONDITIONAL_HANDLES and nid not in outgoing:
            errors.append(f"Node '{nid}' ({ntype}): conditional node has no outgoing edges")

    # Trigger nodes should have at least one outgoing edge
    for nid, ntype in node_types.items():
        if ntype in TRIGGER_TYPES and nid not in outgoing:
            errors.append(f"Node '{nid}' ({ntype}): trigger node has no outgoing edges")

    return errors


def format_errors(errors: list[str]) -> str:
    """Format validation errors as a readable string for the AI."""
    return "\n".join(f"- {e}" for e in errors)
