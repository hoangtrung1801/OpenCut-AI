"""Models for natural-language editor commands."""

from typing import Any

from pydantic import BaseModel, Field


class EditorAction(BaseModel):
    """A structured action the editor can apply to its timeline."""

    type: str
    target: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class CommandRequest(BaseModel):
    """Natural-language command plus optional editor context."""

    command: str = Field(..., min_length=1)
    timeline_state: dict[str, Any] | None = None
    model: str | None = None


class CommandResponse(BaseModel):
    """Structured response returned by the command processor."""

    actions: list[EditorAction] = Field(default_factory=list)
    explanation: str = ""
    confidence: float = 0.5
    raw_response: str | None = None
