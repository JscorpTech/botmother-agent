"""Pydantic models representing the Botmother engine flow JSON schema."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _uid(prefix: str = "node") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ── Enums ────────────────────────────────────────────────────────────────

class NodeType(str, Enum):
    # Triggers
    COMMAND_TRIGGER = "CommandTriggerNode"
    MESSAGE_TRIGGER = "MessageTriggerNode"
    CALLBACK_QUERY_TRIGGER = "CallbackQueryTriggerNode"
    CALLBACK_BUTTON_TRIGGER = "CallbackButtonTriggerNode"
    REPLY_BUTTON_TRIGGER = "ReplyButtonTriggerNode"
    CRON_TRIGGER = "CronTriggerNode"

    # Messages
    SEND_TEXT = "SendTextMessageNode"
    SEND_PHOTO = "SendPhotoNode"
    SEND_VIDEO = "SendVideoNode"
    SEND_AUDIO = "SendAudioNode"
    SEND_FILE = "SendFileNode"
    SEND_ANIMATION = "SendAnimationNode"
    SEND_VOICE = "SendVoiceNode"
    SEND_VIDEO_NOTE = "SendVideoNoteNode"
    SEND_LOCATION = "SendLocationNode"
    SEND_CONTACT = "SendContactNode"
    SEND_POLL = "SendPollNode"
    SEND_STICKER = "SendStickerNode"
    SEND_MEDIA_GROUP = "SendMediaGroupNode"
    SEND_VENUE = "SendVenueNode"
    SEND_DICE = "SendDiceNode"

    # Message operations
    EDIT_MESSAGE = "EditMessageNode"
    DELETE_MESSAGE = "DeleteMessageNode"
    FORWARD_MESSAGE = "ForwardMessageNode"
    COPY_MESSAGE = "CopyMessageNode"
    PIN_MESSAGE = "PinMessageNode"
    UNPIN_MESSAGE = "UnpinMessageNode"
    UNPIN_ALL = "UnpinAllMessagesNode"

    # Interactive
    CHAT_ACTION = "ChatActionNode"
    CALLBACK_ANSWER = "CallbackQueryAnswerNode"
    CHECK_MEMBERSHIP = "CheckMembershipNode"

    # Flow control
    IF_CONDITION = "IfConditionNode"
    RANDOM = "RandomNode"
    FOR_LOOP = "ForLoopNode"
    FOR_LOOP_CONTINUE = "ForLoopContinueNode"
    PAUSE = "PauseNode"

    # Data
    VARIABLE = "VariableNode"
    STATE = "StateNode"
    COLLECTION = "CollectionNode"
    LOAD_COLLECTION_ITEM = "LoadCollectionItemNode"
    LOAD_COLLECTION_LIST = "LoadCollectionListNode"
    UPDATE_COLLECTION = "UpdateCollectionNode"
    DELETE_COLLECTION = "DeleteCollectionNode"

    # Integration
    HTTP_REQUEST = "HTTPRequestNode"
    CUSTOM_CODE = "CustomCodeNode"
    SEND_TO_ADMIN = "SendToAdminNode"
    DELAY = "DelayNode"


class MessageFilterType(str, Enum):
    EQUALS = "equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not-contains"
    STARTS_WITH = "starts_with"
    COMMAND = "command"
    REGEX = "regex"
    ANY = "any"


class MessageType(str, Enum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
    ANIMATION = "animation"
    STICKER = "sticker"
    CONTACT = "contact"
    LOCATION = "location"
    VENUE = "venue"
    POLL = "poll"
    DICE = "dice"


class StateType(str, Enum):
    TEXT = "text"
    CAPTION = "caption"
    CALLBACK = "callback"
    DATA = "data"
    STATIC = "static"
    CONTEXT = "context"
    COLLECTION_ID = "collection_id"
    COLLECTION_FIELD = "collection_field"
    FULL_DATA = "full_data"
    USER_ID = "user_id"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    USERNAME = "username"
    LANGUAGE_CODE = "language_code"
    PHONE_NUMBER = "phone_number"
    LOCATION = "location"
    FILE_ID = "file_id"
    PHOTO = "photo"
    MESSAGE_ID = "message_id"
    DATE = "date"
    COMMAND = "command"


class VariableOperation(str, Enum):
    SET = "set"
    INCREMENT = "increment"
    DECREMENT = "decrement"
    APPEND = "append"
    REMOVE = "remove"
    DELETE = "delete"
    TOGGLE = "toggle"


class ConditionOperator(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "!="
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    GTE = "gte"
    LTE = "lte"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"
    IN = "in"
    REGEX = "regex"
    EXISTS = "exists"


class KeyboardType(str, Enum):
    INLINE = "inline"
    REPLY = "reply"


class ButtonType(str, Enum):
    CALLBACK = "callback"
    URL = "url"
    WEB_APP = "web_app"


# ── Sub-models ───────────────────────────────────────────────────────────

class Position(BaseModel):
    x: float = 0
    y: float = 0


class InlineButton(BaseModel):
    text: str
    type: ButtonType = ButtonType.CALLBACK
    value: str = ""


class ReplyButton(BaseModel):
    text: str
    type: str = "reply"


class Keyboard(BaseModel):
    active: KeyboardType = KeyboardType.INLINE
    inline: Optional[list[list[InlineButton]]] = None
    reply: Optional[list[list[ReplyButton]]] = None


class TriggerState(BaseModel):
    key: str
    type: StateType = StateType.TEXT


class Condition(BaseModel):
    variable: str
    operator: ConditionOperator = ConditionOperator.EQUALS
    value: Any = ""


class ConditionBranch(BaseModel):
    type: str = "if"  # "if", "else_if", "else"
    conditions: list[Condition] = Field(default_factory=list)
    operator: str = "AND"


class CollectionFilter(BaseModel):
    field: str
    operator: str = "equals"
    value: Any = ""
    valueSource: str = "static"
    stateKey: Optional[str] = None


# ── Node ─────────────────────────────────────────────────────────────────

class Node(BaseModel):
    id: str = Field(default_factory=lambda: _uid())
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    position: Position = Field(default_factory=Position)


class Edge(BaseModel):
    id: str = Field(default_factory=lambda: _uid("edge"))
    source: str
    target: str
    type: str = "smart-edge"
    sourceHandle: Optional[str] = None
    targetHandle: Optional[str] = None


class Flow(BaseModel):
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)


# ── Helper builders ──────────────────────────────────────────────────────

class FlowBuilder:
    """Utility to programmatically construct a Flow."""

    def __init__(self) -> None:
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self._y = 100

    def add_node(self, node_type: str, data: dict[str, Any], node_id: str | None = None) -> str:
        nid = node_id or _uid()
        self.nodes.append(Node(
            id=nid,
            type=node_type,
            data=data,
            position=Position(x=100, y=self._y),
        ))
        self._y += 200
        return nid

    def connect(self, source: str, target: str, source_handle: str | None = None) -> None:
        self.edges.append(Edge(
            source=source,
            target=target,
            sourceHandle=source_handle,
        ))

    def build(self) -> Flow:
        return Flow(nodes=self.nodes, edges=self.edges)

    def to_dict(self) -> dict:
        return self.build().model_dump(exclude_none=True)
