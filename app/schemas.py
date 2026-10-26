"""Pydantic schemas and strict action definitions for BrowserPilot Vision."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Common patterns for executable or injection attempts
DANGEROUS_PATTERNS = [
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"data\s*:\s*text/html", re.IGNORECASE),
    re.compile(r"<\s*script\b", re.IGNORECASE),
    re.compile(r"\b(eval|exec|import|subprocess|os\.system)\s*\(", re.IGNORECASE),
    re.compile(r"__import__", re.IGNORECASE),
    re.compile(r"\bcmd\.exe\b|\bpowershell\b|\b/bin/sh\b|\b/bin/bash\b", re.IGNORECASE),
]


def assert_safe_text(val: str, field_name: str) -> str:
    """Ensure no executable code or injection patterns exist in input text."""
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(val):
            raise ValueError(f"Dangerous or executable code detected in '{field_name}': rejected by safety filter.")
    return val


class ActionType(str, Enum):
    CLICK = "click"
    FILL = "fill"
    GOTO = "goto"
    SCROLL = "scroll"
    WAIT = "wait"
    FINISH = "finish"


class ScrollDirection(str, Enum):
    UP = "up"
    DOWN = "down"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    UNVERIFIED = "unverified"
    FAILED = "failed"
    BLOCKED = "blocked"
    STEP_LIMIT_REACHED = "step_limit_reached"
    CANCELLED = "cancelled"


class TargetCandidate(BaseModel):
    """Structured representation of an interactive target on the page."""
    model_config = ConfigDict(extra="forbid")

    id: int = Field(description="Unique numbered index on current page")
    role: str = Field(description="Semantic role (e.g., button, link, textbox)")
    name: str = Field(description="Accessible name or visible text")
    selector: str = Field(description="Accessibility or CSS selector")
    tag: str = Field(default="", description="HTML tag name")
    disabled: bool = Field(default=False, description="Whether element is disabled")
    input_type: Optional[str] = Field(default=None, description="Input type if applicable")
    placeholder: Optional[str] = Field(default=None, description="Placeholder text")
    href: Optional[str] = Field(default=None, description="Href link destination if applicable")


class PageObservation(BaseModel):
    """Compact structured observation of browser state."""
    model_config = ConfigDict(extra="forbid")

    url: str
    title: str
    visible_text: str = Field(description="Bounded text summary of visible content")
    interactive_elements: List[TargetCandidate] = Field(default_factory=list)
    char_count: int = 0
    truncated: bool = False
    screenshot_path: Optional[str] = None


class ActionDecision(BaseModel):
    """Strict action schema proposed by LLM."""
    model_config = ConfigDict(extra="forbid")

    thought: str = Field(
        ...,
        max_length=500,
        description="Concise rationale for choosing this action",
    )
    action: ActionType = Field(
        ...,
        description="One of: click, fill, goto, scroll, wait, finish",
    )
    # Target can be an element ID (as string or int) or accessible name/selector
    target: Optional[str] = Field(
        default=None,
        max_length=250,
        description="Target element ID, accessible name, or selector for click/fill",
    )
    value: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Text to type into input field for fill action",
    )
    url: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Target destination URL for goto action",
    )
    direction: Optional[ScrollDirection] = Field(
        default=None,
        description="Direction to scroll: 'up' or 'down'",
    )
    amount: Optional[int] = Field(
        default=500,
        ge=50,
        le=2000,
        description="Pixels to scroll (between 50 and 2000)",
    )
    seconds: Optional[float] = Field(
        default=1.0,
        ge=0.5,
        le=10.0,
        description="Seconds to pause (between 0.5 and 10.0)",
    )
    answer: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Final answer or task resolution statement for finish action",
    )
    evidence: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Observable browser proof supporting the finish answer",
    )

    @field_validator("thought", "target", "value", "url", "answer", "evidence")
    @classmethod
    def validate_safety(cls, v: Optional[str], info: Any) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if v:
                assert_safe_text(v, info.field_name)
        return v

    @model_validator(mode="after")
    def validate_action_fields(self) -> ActionDecision:
        act = self.action

        if act == ActionType.CLICK:
            if not self.target or not self.target.strip():
                raise ValueError("Action 'click' requires a non-empty 'target' field.")

        elif act == ActionType.FILL:
            if not self.target or not self.target.strip():
                raise ValueError("Action 'fill' requires a non-empty 'target' field.")
            if self.value is None or self.value == "":
                raise ValueError("Action 'fill' requires a non-empty 'value' field.")

        elif act == ActionType.GOTO:
            if not self.url or not self.url.strip():
                raise ValueError("Action 'goto' requires a non-empty 'url' field.")

        elif act == ActionType.SCROLL:
            if self.direction is None:
                self.direction = ScrollDirection.DOWN
            if self.amount is None:
                self.amount = 500

        elif act == ActionType.WAIT:
            if self.seconds is None:
                self.seconds = 1.0

        elif act == ActionType.FINISH:
            if not self.answer or not self.answer.strip():
                raise ValueError("Action 'finish' requires a non-empty 'answer' field.")

        return self


class ActionResult(BaseModel):
    """Result of an action execution with verification."""
    model_config = ConfigDict(extra="forbid")

    action: ActionDecision
    success: bool
    message: str
    error: Optional[str] = None
    error_category: Optional[str] = None
    duration: float = 0.0
    url_before: str = ""
    url_after: str = ""
    verification_passed: bool = False
    verification_evidence: Optional[str] = None
    timestamp: str = ""
    recovery_attempt: int = 0


class TaskRequest(BaseModel):
    """API or UI request to start a browser task."""
    model_config = ConfigDict(extra="forbid")

    task: str = Field(..., min_length=3, max_length=1000, description="Natural language goal")
    start_url: str = Field(..., min_length=4, max_length=1000, description="Initial website URL")
    model: Optional[str] = Field(default=None, max_length=100, description="Configured Ollama model")
    max_steps: Optional[int] = Field(default=None, ge=1, le=50, description="Max action steps")
    use_vision: bool = Field(default=False, description="Enable vision fallback with screenshot")

    @field_validator("task")
    @classmethod
    def validate_task_text(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 3:
            raise ValueError("Task description must contain at least 3 non-whitespace characters.")
        return assert_safe_text(cleaned, "task")

    @field_validator("start_url")
    @classmethod
    def validate_start_url(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 4:
            raise ValueError("Start URL must contain at least 4 non-whitespace characters.")
        return assert_safe_text(cleaned, "start_url")


class TaskStepRecord(BaseModel):
    """Execution history entry for logging and inspection."""
    step: int
    timestamp: str
    thought: str
    action: str
    target: Optional[str] = None
    value: Optional[str] = None
    url: Optional[str] = None
    success: bool
    verification_passed: bool
    message: str
    evidence: Optional[str] = None
    duration: float = 0.0
    error_category: Optional[str] = None


class TaskResponse(BaseModel):
    """Task status response model."""
    task_id: str
    status: TaskStatus
    task: str
    start_url: str
    model: str
    result: Optional[str] = None
    evidence: Optional[str] = None
    steps_taken: int = 0
    max_steps: int = 12
    created_at: str
    updated_at: str
    error: Optional[str] = None
    history: List[TaskStepRecord] = Field(default_factory=list)
