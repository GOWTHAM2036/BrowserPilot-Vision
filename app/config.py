"""Configuration settings for BrowserPilot Vision."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Optional, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings with environment variable fallback and strict validation."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Ollama API settings
    ollama_base_url: str = Field(default="http://localhost:11434", description="Ollama API base URL")
    default_model: str = Field(default="gemma3:4b", description="Default model name")
    supported_models: List[str] = Field(
        default_factory=lambda: [
            "gemma3:4b",
            "qwen3:4b",
            "qwen2.5:1.5b-instruct-q4_K_M",
        ],
        description="Supported local models",
    )

    # Inference & Hardware limits (Tuned for 4GB VRAM)
    context_size: int = Field(default=4096, ge=1024, le=16384, description="Context window token limit")
    request_timeout: float = Field(default=120.0, ge=5.0, le=300.0, description="Ollama LLM call timeout in seconds")

    # Agent constraints
    max_agent_steps: int = Field(default=12, ge=1, le=50, description="Maximum actions per task")
    max_observation_chars: int = Field(default=3000, ge=500, le=10000, description="Max visible text per page")
    max_recovery_attempts: int = Field(default=2, ge=0, le=5, description="Max retry attempts for failed action")
    recent_history_limit: int = Field(default=4, ge=1, le=10, description="Recent steps to include in LLM prompt")

    # Security & Safety policies
    allowed_hosts: Union[List[str], str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"],
        description="List of allowed hostname domains",
    )
    enforce_https: bool = Field(default=False, description="Require HTTPS (false for local demo sites)")

    # Browser automation
    headless: bool = Field(default=True, description="Run Playwright in headless mode")
    browser_action_timeout: int = Field(default=5000, ge=1000, le=30000, description="Playwright action timeout in ms")
    page_load_timeout: int = Field(default=15000, ge=2000, le=60000, description="Page navigation timeout in ms")

    # Storage and paths
    log_dir: Path = Field(default_factory=lambda: BASE_DIR / "data", description="Directory for jsonl logs")
    screenshots_dir: Path = Field(default_factory=lambda: BASE_DIR / "data" / "screenshots", description="Screenshots")

    @field_validator("log_dir", "screenshots_dir", mode="before")
    @classmethod
    def resolve_relative_path(cls, v: Any) -> Path:
        if v is None:
            return BASE_DIR / "data"
        p = Path(v)
        if not p.is_absolute():
            return BASE_DIR / p
        return p

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            return [h.strip().lower() for h in v.split(",") if h.strip()]
        if isinstance(v, list):
            return [str(h).strip().lower() for h in v if str(h).strip()]
        return ["localhost", "127.0.0.1"]

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_url(cls, v: str) -> str:
        v = v.rstrip("/")
        if not v.startswith("http://") and not v.startswith("https://"):
            raise ValueError(f"Ollama URL must start with http:// or https://, got: {v}")
        return v

    def setup_directories(self) -> None:
        """Ensure runtime directories exist."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
settings.setup_directories()
