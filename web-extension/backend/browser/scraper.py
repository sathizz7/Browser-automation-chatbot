"""
Page Scraper — Playwright-Based DOM Extraction + Screenshot (Skyvern-Style)

Replaces the old content_script.js DOM capture.
Instead of running JavaScript inside the page via a Chrome Extension,
this module uses Playwright to:

1. Inject a small JS script that tags interactive elements with refs (B#, I#, L#, S#)
2. Extract structured element data (text, label, bounds, attributes)
3. Take a viewport screenshot (PNG → base64 for the Vision LLM)
4. Extract page text and headings for context

The result is a ScrapedPage dataclass containing everything the LLM needs.
"""

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("browser-agent.scraper")


# ─────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────

@dataclass
class ElementData:
    """A single interactive element on the page."""
    ref: str                    # e.g. "B0", "I3", "L12", "S1"
    tag: str                    # "button", "input", "link", "select"
    text: str = ""
    label: str = ""
    type: str = ""              # input type (text, email, password, etc.)
    href: str = ""
    placeholder: str = ""
    value: str = ""
    disabled: bool = False
    required: bool = False
    bounds: dict = field(default_factory=dict)   # {x, y, width, height}
    options: list[dict] = field(default_factory=list)  # for <select>
    identifiers: dict = field(default_factory=dict)    # id, name, aria-label, etc.


@dataclass
class ScrapedPage:
    """Complete result of scraping a page — DOM + screenshot."""
    url: str
    title: str
    domain: str
    elements: list[ElementData]
    element_count: int
    headings: list[str]
    page_text: str
    screenshot_base64: str      # PNG screenshot as base64 string
    form_count: int = 0
    timestamp: int = 0


# ─────────────────────────────────────────────
# The JavaScript that runs inside the page
# ─────────────────────────────────────────────

# This is injected via page.evaluate() — it tags elements and extracts data.
# It mirrors the production-grade logic from the old agent.js / content_script.js.

SCRAPER_JS = """
() => {
    // ── Helpers ──────────────────────────────────────────

    function getVisibleText(el) {
        const tag = el.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA") return el.value || el.placeholder || "";
        if (tag === "SELECT") {
            const sel = el.options[el.selectedIndex];
            return sel ? sel.text : "";
        }
        return (el.innerText || el.textContent || "").trim().substring(0, 150);
    }

    function isVisible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === "none" || style.visibility === "hidden") return false;
        if (parseFloat(style.opacity) < 0.1) return false;
        const rect = el.getBoundingClientRect();
        if (rect.width < 1 || rect.height < 1) return false;
        if (el.offsetParent === null && style.position !== "fixed" && style.position !== "sticky") return false;
        return true;
    }

    function getLabel(el) {
        if (el.id) {
            const lbl = document.querySelector('label[for="' + el.id + '"]');
            if (lbl) return lbl.innerText.trim();
        }
        if (el.labels && el.labels.length > 0) return el.labels[0].innerText.trim();
        const ariaLabel = el.getAttribute("aria-label");
        if (ariaLabel) return ariaLabel;
        const labelledBy = el.getAttribute("aria-labelledby");
        if (labelledBy) {
            const labelEl = document.getElementById(labelledBy);
            if (labelEl) return labelEl.innerText.trim();
        }
        const parentLabel = el.closest("label");
        if (parentLabel) { const t = parentLabel.innerText.trim(); if (t) return t; }
        const prev = el.previousElementSibling;
        if (prev && ["LABEL","SPAN","DIV"].includes(prev.tagName)) {
            const t = prev.innerText.trim();
            if (t && t.length < 100) return t;
        }
        if (el.placeholder) return el.placeholder;
        if (el.name) return el.name.replace(/[_-]/g, " ");
        return "";
    }

    function getIdentifiers(el) {
        const ids = {};
        if (el.dataset && el.dataset.testid) ids.testId = el.dataset.testid;
        if (el.getAttribute("aria-label")) ids.ariaLabel = el.getAttribute("aria-label");
        if (el.id) ids.id = el.id;
        if (el.name) ids.name = el.name;
        if (el.title) ids.title = el.title;
        return ids;
    }

    function getBounds(el) {
        const r = el.getBoundingClientRect();
        return { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) };
    }

    // ── Clear old refs ───────────────────────────────────
    document.querySelectorAll("[data-agent-ref]").forEach(el => el.removeAttribute("data-agent-ref"));

    // ── Scan interactive elements ────────────────────────
    const MAX_ELEMENTS = 200;
    const elements = [];
    const counters = { input: 0, select: 0, button: 0, link: 0 };

    const selector = 'input, select, textarea, button, a[href], [role="button"], [role="link"], [onclick], [tabindex]:not([tabindex="-1"])';
    const allElements = document.querySelectorAll(selector);

    for (const el of allElements) {
        if (!isVisible(el)) continue;
        if (elements.length >= MAX_ELEMENTS) break;

        const tag = el.tagName.toLowerCase();
        const role = el.getAttribute("role");
        let elementData = null;
        let ref = "";

        if (tag === "input" || tag === "textarea") {
            if (el.type === "hidden") continue;
            if (el.type === "submit" || el.type === "button") {
                ref = "B" + counters.button++;
                elementData = { ref, tag: "button", type: el.type, text: getVisibleText(el), label: getLabel(el), identifiers: getIdentifiers(el), disabled: el.disabled, bounds: getBounds(el) };
            } else {
                ref = "I" + counters.input++;
                elementData = { ref, tag: tag === "textarea" ? "textarea" : "input", type: el.type || "text", text: "", label: getLabel(el), placeholder: el.placeholder || "", value: el.value || "", required: el.required || el.getAttribute("aria-required") === "true", identifiers: getIdentifiers(el), disabled: el.disabled, bounds: getBounds(el) };
            }
        } else if (tag === "select") {
            ref = "S" + counters.select++;
            const options = Array.from(el.options).map(o => ({ value: o.value, text: o.text.trim(), selected: o.selected })).slice(0, 20);
            elementData = { ref, tag: "select", label: getLabel(el), options, selectedValue: el.value, selectedText: (el.options[el.selectedIndex] || {}).text || "", required: el.required, identifiers: getIdentifiers(el), disabled: el.disabled, bounds: getBounds(el) };
        } else if (tag === "button" || role === "button" || el.onclick) {
            ref = "B" + counters.button++;
            elementData = { ref, tag: "button", type: el.type || "button", text: getVisibleText(el), label: getLabel(el), identifiers: getIdentifiers(el), disabled: el.disabled, bounds: getBounds(el) };
        } else if (tag === "a" || role === "link") {
            const text = getVisibleText(el);
            if (!text && !el.getAttribute("aria-label")) continue;
            ref = "L" + counters.link++;
            elementData = { ref, tag: "link", text, label: el.getAttribute("aria-label") || "", href: el.href || "", identifiers: getIdentifiers(el), bounds: getBounds(el) };
        }

        if (elementData && ref) {
            el.setAttribute("data-agent-ref", ref);
            elements.push(elementData);
        }
    }

    // ── Extract headings ────────────────────────────────
    const headings = Array.from(document.querySelectorAll("h1, h2, h3, h4"))
        .map(h => (h.innerText || "").trim()).filter(Boolean).slice(0, 10);

    // ── Extract page text ───────────────────────────────
    const mainContent = document.querySelector("main, article, [role='main'], .content, #content");
    const source = mainContent || document.body;
    const pageText = (source.innerText || "").replace(/\\s+/g, " ").trim().substring(0, 5000);

    return {
        url: window.location.href,
        title: document.title,
        domain: window.location.hostname,
        elements,
        element_count: elements.length,
        headings,
        pageText,
        formCount: document.forms.length,
        timestamp: Date.now(),
        counters,
    };
}
"""


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

async def scrape_page(page: Page, take_screenshot: bool = True) -> ScrapedPage:
    """
    Scrape the current page: extract DOM elements + take screenshot.

    This is the Skyvern-style replacement for the old content_script.js
    getDOMSnapshot(). Instead of running inside the page via a Chrome
    Extension, we inject a script via Playwright's page.evaluate().

    Args:
        page: Playwright Page object.
        take_screenshot: Whether to capture a screenshot (default True).

    Returns:
        ScrapedPage with elements, screenshot, headings, page text.
    """
    logger.info(f"📄 Scraping page: {page.url}")

    # 1. Inject JS and extract DOM data
    try:
        raw = await page.evaluate(SCRAPER_JS)
    except Exception as e:
        logger.error(f"❌ DOM extraction failed: {e}")
        return ScrapedPage(
            url=page.url,
            title=await page.title(),
            domain="",
            elements=[],
            element_count=0,
            headings=[],
            page_text="",
            screenshot_base64="",
        )

    # 2. Parse element data into dataclasses
    elements = []
    for el in raw.get("elements", []):
        elements.append(ElementData(
            ref=el.get("ref", ""),
            tag=el.get("tag", ""),
            text=el.get("text", ""),
            label=el.get("label", ""),
            type=el.get("type", ""),
            href=el.get("href", ""),
            placeholder=el.get("placeholder", ""),
            value=el.get("value", ""),
            disabled=el.get("disabled", False),
            required=el.get("required", False),
            bounds=el.get("bounds", {}),
            options=el.get("options", []),
            identifiers=el.get("identifiers", {}),
        ))

    # 3. Take screenshot
    screenshot_b64 = ""
    if take_screenshot:
        try:
            screenshot_bytes = await page.screenshot(type="png")
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            logger.info(f"📸 Screenshot captured ({len(screenshot_bytes)} bytes)")
        except Exception as e:
            logger.warning(f"⚠️ Screenshot failed: {e}")

    counters = raw.get("counters", {})
    logger.info(
        f"✅ Scraped {raw.get('element_count', 0)} elements "
        f"(B:{counters.get('button',0)} I:{counters.get('input',0)} "
        f"L:{counters.get('link',0)} S:{counters.get('select',0)})"
    )

    return ScrapedPage(
        url=raw.get("url", page.url),
        title=raw.get("title", ""),
        domain=raw.get("domain", ""),
        elements=elements,
        element_count=raw.get("element_count", len(elements)),
        headings=raw.get("headings", []),
        page_text=raw.get("pageText", ""),
        screenshot_base64=screenshot_b64,
        form_count=raw.get("formCount", 0),
        timestamp=raw.get("timestamp", 0),
    )


def format_elements_for_llm(scraped: ScrapedPage) -> str:
    """
    Format scraped elements into a concise text block for the LLM prompt.

    Example output:
        B0 [button] "Submit" (label: Submit Form)
        I0 [input:text] "" (label: First Name, placeholder: Enter name)
        L3 [link] "About Us" → /about
        S0 [select] "English" (label: Language, options: English, Hindi, Telugu)
    """
    lines = []
    for el in scraped.elements:
        parts = [f'{el.ref} [{el.tag}']
        if el.type and el.tag in ("input", "button"):
            parts[0] += f':{el.type}'
        parts[0] += ']'

        if el.text:
            parts.append(f'"{el.text}"')
        elif el.value:
            parts.append(f'value="{el.value}"')
        elif el.placeholder:
            parts.append(f'placeholder="{el.placeholder}"')
        else:
            parts.append('""')

        extras = []
        if el.label:
            extras.append(f'label: {el.label}')
        if el.href:
            # Shorten long URLs
            href = el.href
            if len(href) > 60:
                href = href[:57] + "..."
            extras.append(f'→ {href}')
        if el.disabled:
            extras.append('DISABLED')
        if el.required:
            extras.append('REQUIRED')
        if el.options:
            opt_texts = [o.get("text", "") for o in el.options[:5]]
            if len(el.options) > 5:
                opt_texts.append(f"...+{len(el.options)-5} more")
            extras.append(f'options: {", ".join(opt_texts)}')

        if extras:
            parts.append(f'({"; ".join(extras)})')

        lines.append(" ".join(parts))

    return "\n".join(lines)
