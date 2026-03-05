"""Adaptable allowlist system for browser automation.

Modes:
  - allow_all:      any site works, except blocked_domains
  - allowlist_only:  only domains in allowed_domains
  - blocklist_only:  all sites except blocked_domains

Loaded from allowlist.json at startup. Swap to DB/env later by
replacing the _load() function — interface stays the same.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_DEFAULT_CONFIG_PATH = Path(__file__).parent / "allowlist.json"

VALID_MODES = {"allow_all", "allowlist_only", "blocklist_only"}


@dataclass
class SiteStrategy:
    """Per-site automation strategy hints."""
    checkout_stop_at: str = "review_order"
    notes: str = ""


@dataclass
class AllowlistManager:
    """Runtime allowlist checker."""
    mode: str = "allow_all"
    allowed_domains: set[str] = field(default_factory=set)
    blocked_domains: set[str] = field(default_factory=set)
    site_strategies: dict[str, SiteStrategy] = field(default_factory=dict)

    # ── public API ──────────────────────────────────────────

    def is_allowed(self, url: str) -> bool:
        """Check if a URL is permitted under the current mode."""
        domain = self._extract_domain(url)
        if not domain:
            return False

        if self.mode == "allow_all":
            return domain not in self.blocked_domains

        if self.mode == "allowlist_only":
            return domain in self.allowed_domains

        if self.mode == "blocklist_only":
            return domain not in self.blocked_domains

        return False

    def get_strategy(self, url: str) -> SiteStrategy | None:
        """Return site-specific strategy if one is configured."""
        domain = self._extract_domain(url)
        return self.site_strategies.get(domain) if domain else None

    # ── internals ───────────────────────────────────────────

    @staticmethod
    def _extract_domain(url: str) -> str | None:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if hostname.startswith("www."):
            hostname = hostname[4:]
        return hostname or None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AllowlistManager:
        mode = data.get("mode", "allow_all")
        if mode not in VALID_MODES:
            raise ValueError(f"Invalid allowlist mode: {mode!r}")

        strategies: dict[str, SiteStrategy] = {}
        for domain, strat_dict in data.get("site_strategies", {}).items():
            strategies[domain.lower()] = SiteStrategy(
                checkout_stop_at=strat_dict.get("checkout_stop_at", "review_order"),
                notes=strat_dict.get("notes", ""),
            )

        return cls(
            mode=mode,
            allowed_domains={d.lower() for d in data.get("allowed_domains", [])},
            blocked_domains={d.lower() for d in data.get("blocked_domains", [])},
            site_strategies=strategies,
        )

    @classmethod
    def load(cls, config_path: Path | None = None) -> AllowlistManager:
        """Load allowlist from JSON config file."""
        path = config_path or _DEFAULT_CONFIG_PATH
        if not path.exists():
            return cls()  # permissive default
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)
