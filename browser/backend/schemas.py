"""Pydantic schemas for the browser automation backend.

Includes:
  - UserProfile:        citizen profile data for form-filling
  - AutomateRequest:    request to run an automation task
  - AutomateResult:     structured result from the agent
  - ChatRequest/Resp:   conversational chat endpoint models
  - ScrapedProduct:     migrated from original scraper (backward compat)
  - ScrapeResult:       migrated collection wrapper
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


# ── Enums ──────────────────────────────────────────────────

class TaskType(str, Enum):
    READ_PAGE = "read_page"
    FILL_FORM = "fill_form"
    NAVIGATE = "navigate"
    CHECKOUT_FLOW = "checkout_flow"
    SCRAPE = "scrape"


# ── User Profile ───────────────────────────────────────────

class UserProfile(BaseModel):
    """Citizen profile used for form-filling automation."""
    model_config = ConfigDict(extra="allow")

    full_name: str = Field(default="", max_length=200)
    first_name: str = Field(default="", max_length=100)
    last_name: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=20)
    address_line1: str = Field(default="", max_length=300)
    address_line2: str = Field(default="", max_length=300)
    city: str = Field(default="", max_length=100)
    state: str = Field(default="", max_length=100)
    zip_code: str = Field(default="", max_length=20)
    country: str = Field(default="India", max_length=100)

    @model_validator(mode="after")
    def derive_names(self) -> "UserProfile":
        """Auto-derive first/last from full_name if not provided."""
        if self.full_name and not self.first_name:
            parts = self.full_name.strip().split()
            self.first_name = parts[0] if parts else ""
            self.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
        return self


# ── Automate Request / Result ──────────────────────────────

class AutomateRequest(BaseModel):
    """Request body for POST /automate."""
    model_config = ConfigDict(extra="forbid")

    task_type: TaskType
    target_url: str = Field(min_length=1)
    user_message: str = Field(default="", max_length=2000)
    user_profile: UserProfile | None = None
    page_context: dict[str, Any] | None = None
    max_steps: int | None = None


class StepLog(BaseModel):
    """A single step in the agent execution log."""
    step: int
    action: str
    detail: str = ""


class AutomateResult(BaseModel):
    """Structured result from the browser automation agent."""
    success: bool
    task_type: TaskType
    message: str = ""
    current_url: str = ""
    steps_taken: int = 0
    step_log: list[StepLog] = Field(default_factory=list)
    extracted_data: dict[str, Any] | None = None
    error: str | None = None


# ── Chat ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(default="default")
    page_url: str = ""
    page_context: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    message: str
    suggested_actions: list[str] = Field(default_factory=list)
    session_id: str = "default"


# ── Scraped Product (migrated, backward-compat) ───────────

_PRICE_RE = re.compile(r"(?P<currency>[A-Za-z$£€])\s*(?P<amount>\d+(?:\.\d{1,2})?)")


def _normalize_space(value: str) -> str:
    return " ".join(value.split())


class ScrapedProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=300)
    product_url: HttpUrl
    price_raw: str = Field(min_length=1, max_length=40)
    price_value: float | None = Field(default=None, ge=0)
    currency: str = Field(default="GBP", min_length=3, max_length=3)
    rating: int = Field(ge=1, le=5, description="Integer star rating from 1-5")
    in_stock: bool
    availability_text: str = Field(min_length=1, max_length=100)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = _normalize_space(value)
        if len(value) < 3:
            raise ValueError("title is too short after trimming")
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        value = value.upper().strip()
        if value not in {"GBP", "USD", "EUR"}:
            raise ValueError("currency must be one of GBP, USD, EUR")
        return value

    @model_validator(mode="after")
    def parse_and_validate_price(self) -> "ScrapedProduct":
        raw = self.price_raw.strip()
        match = _PRICE_RE.search(raw)
        if not match:
            raise ValueError(f"price_raw has invalid format: {raw!r}")

        symbol = match.group("currency")
        amount = float(match.group("amount"))
        symbol_to_currency = {"£": "GBP", "$": "USD", "€": "EUR"}
        if symbol in symbol_to_currency:
            expected_currency = symbol_to_currency[symbol]
            if self.currency != expected_currency:
                raise ValueError(
                    f"currency mismatch: parsed {expected_currency} from price_raw, got {self.currency}"
                )

        if self.price_value is None:
            self.price_value = amount
        elif abs(self.price_value - amount) > 0.01:
            raise ValueError(f"price_value {self.price_value} does not match price_raw {amount}")

        if self.in_stock and "stock" not in self.availability_text.lower():
            raise ValueError("in_stock=true but availability_text does not indicate stock")

        return self


class ScrapeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_case: str = Field(min_length=5, max_length=200)
    query: str = Field(min_length=2, max_length=120)
    source_url: HttpUrl
    source_domain: str = Field(min_length=3, max_length=120)
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    items: list[ScrapedProduct] = Field(min_length=1)

    @field_validator("source_domain")
    @classmethod
    def validate_source_domain(cls, value: str) -> str:
        value = value.lower().strip()
        if value.startswith("www."):
            value = value[4:]
        if "." not in value:
            raise ValueError("source_domain must be a valid domain name")
        return value

    @model_validator(mode="after")
    def validate_collection(self) -> "ScrapeResult":
        expected_domain = self.source_domain
        source_host = (urlparse(self.source_url.unicode_string()).hostname or "").lower()
        if source_host.startswith("www."):
            source_host = source_host[4:]
        if source_host != expected_domain:
            raise ValueError(
                f"source_domain {expected_domain} does not match source_url host {source_host}"
            )

        seen_urls: set[str] = set()
        for item in self.items:
            item_host = (urlparse(str(item.product_url)).hostname or "").lower()
            if item_host.startswith("www."):
                item_host = item_host[4:]
            if item_host != expected_domain:
                raise ValueError(f"item URL host mismatch: {item.product_url}")

            item_url = str(item.product_url)
            if item_url in seen_urls:
                raise ValueError(f"duplicate product_url found: {item_url}")
            seen_urls.add(item_url)

        return self
