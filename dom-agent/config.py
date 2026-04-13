"""Configurable parameters for the DOM-agent backend.

All values can be overridden via environment variables or .env file.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings


class AgentConfig(BaseSettings):
    """Agent-wide settings — loaded from .env / environment."""

    # ── LLM ────────────────────────────────────────────────
    llm_model: str = "gemini/gemini-2.5-flash"
    gemini_api_key: str = ""
    google_api_key: str = ""

    # ── DOM Snapshot ───────────────────────────────────────
    max_elements: int = 50
    """Max interactive elements sent to the LLM per snapshot."""

    # ── Action batching ────────────────────────────────────
    max_actions_per_batch: int = 10
    """Max actions the LLM may return in a single plan response."""

    # ── Human-like typing ──────────────────────────────────
    type_delay_min_ms: int = 50
    type_delay_max_ms: int = 130

    # ── State observers ────────────────────────────────────
    dom_settle_timeout_ms: int = 3000
    network_idle_ms: int = 500
    mutation_settle_ms: int = 300

    # ── Loop detection ─────────────────────────────────────
    loop_detection_window: int = 5
    """Number of recent action batches to track for repetition."""
    loop_abort_threshold: int = 3
    """Abort after this many repeated identical batches."""

    # ── Server ─────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 8001
    cors_origins: list[str] = ["chrome-extension://*", "http://localhost:*"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


# Singleton — import this everywhere
settings = AgentConfig()
