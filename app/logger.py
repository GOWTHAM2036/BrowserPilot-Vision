"""JSON Lines execution logger with sensitive data masking and fault tolerance for BrowserPilot Vision."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import settings


# Sensitive key patterns to mask
SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|token|secret|credential|cookie|auth|authorization|api[-_]?key|credit[-_]?card|cvv|ssn)",
    re.IGNORECASE,
)

# Sensitive value patterns (e.g. bearer tokens, card numbers)
SENSITIVE_VALUE_PATTERN = re.compile(
    r"(bearer\s+[A-Za-z0-9_\-\.]+|\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b)",
    re.IGNORECASE,
)


def mask_sensitive_data(obj: Any) -> Any:
    """Recursively mask sensitive values in dictionaries, lists, and strings."""
    if isinstance(obj, dict):
        masked = {}
        for k, v in obj.items():
            if SENSITIVE_KEY_PATTERN.search(str(k)):
                masked[k] = "[MASKED_SECRET]"
            else:
                masked[k] = mask_sensitive_data(v)
        return masked
    elif isinstance(obj, list):
        return [mask_sensitive_data(item) for item in obj]
    elif isinstance(obj, str):
        return SENSITIVE_VALUE_PATTERN.sub("[MASKED_TOKEN]", obj)
    return obj


class TaskLogger:
    """Writes structured execution records to JSON Lines files with guaranteed fault tolerance."""

    def __init__(self, task_id: str, log_dir: Optional[Path] = None):
        self.task_id = task_id
        try:
            self.log_dir = log_dir or settings.log_dir
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self.log_file = self.log_dir / f"{task_id}.jsonl"
        except Exception:
            # Fallback path if custom dir cannot be created
            self.log_dir = Path("data")
            self.log_file = self.log_dir / f"{task_id}.jsonl"

    def log_event(
        self,
        event_type: str,
        data: Dict[str, Any],
        step: Optional[int] = None,
    ) -> bool:
        """Append a JSONL event entry to the log file. Logging failures must never crash the agent."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            entry = {
                "task_id": self.task_id,
                "timestamp": now,
                "event_type": event_type,
                "step": step,
                "data": mask_sensitive_data(data),
            }
            line = json.dumps(entry, default=str)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            return True
        except Exception as e:
            # Gracefully handle write errors without crashing caller
            app_logger.warning(f"TaskLogger failed to write event ({event_type}): {e}")
            return False

    def log_action(
        self,
        step: int,
        action: Dict[str, Any],
        outcome: Dict[str, Any],
        verification_passed: bool,
        verification_evidence: Optional[str] = None,
        recovery_attempt: int = 0,
        observation_summary: Optional[str] = None,
        error_category: Optional[str] = None,
        duration: float = 0.0,
    ) -> bool:
        """Log a structured action execution event with required metrics."""
        action_type = action.get("action", "unknown")
        sanitized_args = {
            k: v for k, v in action.items() if k not in ("action", "thought")
        }

        execution_status = (
            "success" if outcome.get("success") else "failed"
        )
        if outcome.get("error") and "safety" in str(outcome.get("error")).lower():
            execution_status = "blocked"

        payload = {
            "task_id": self.task_id,
            "step_number": step,
            "action_type": action_type,
            "sanitized_action_args": mask_sensitive_data(sanitized_args),
            "execution_status": execution_status,
            "brief_observation_summary": (observation_summary or outcome.get("message") or "")[:250],
            "error_category": error_category or outcome.get("error_category"),
            "duration": round(duration, 3),
            "verification_passed": verification_passed,
            "verification_evidence": verification_evidence,
            "recovery_attempt": recovery_attempt,
            "thought": action.get("thought", ""),
            "outcome": outcome,
        }
        return self.log_event("action_execution", payload, step=step)

    def log_error(
        self,
        step: Optional[int],
        error_message: str,
        error_category: str = "general_error",
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Log an error event safely."""
        payload = {
            "error": error_message,
            "error_category": error_category,
            "context": context or {},
        }
        return self.log_event("error", payload, step=step)

    def read_logs(self) -> list[Dict[str, Any]]:
        """Read all logged events for this task."""
        try:
            if not self.log_file.exists():
                return []
            events = []
            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            return events
        except Exception:
            return []


# Standard console logger for application level info
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
app_logger = logging.getLogger("browserpilot")
