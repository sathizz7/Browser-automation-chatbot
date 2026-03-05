"""Task prompt builders for the browser automation agent.

Each builder returns a prompt string tailored to the task type,
injecting user profile data and page context as needed.
"""
from __future__ import annotations

from typing import Any

from schemas import TaskType, UserProfile


def _format_profile(profile: UserProfile | None) -> str:
    """Format user profile as key-value block for the LLM prompt."""
    if not profile:
        return "No user profile provided."
    lines = []
    for key, val in profile.model_dump(exclude_none=True).items():
        if val:
            label = key.replace("_", " ").title()
            lines.append(f"  - {label}: {val}")
    return "\n".join(lines) if lines else "No profile data available."


def _format_page_context(ctx: dict[str, Any] | None) -> str:
    """Format page context snapshot for the LLM prompt."""
    if not ctx:
        return "No page context provided."
    parts = []
    if ctx.get("url"):
        parts.append(f"  URL: {ctx['url']}")
    if ctx.get("title"):
        parts.append(f"  Title: {ctx['title']}")
    if ctx.get("forms"):
        parts.append(f"  Forms detected: {len(ctx['forms'])}")
        for i, form in enumerate(ctx["forms"][:5]):
            fields = form.get("fields", [])
            field_names = [f.get("name") or f.get("id", "?") for f in fields[:10]]
            parts.append(f"    Form {i}: fields = {field_names}")
    return "\n".join(parts) if parts else "No page context available."


def build_prompt(
    task_type: TaskType,
    target_url: str,
    user_message: str = "",
    profile: UserProfile | None = None,
    page_context: dict[str, Any] | None = None,
) -> str:
    """Dispatch to the correct prompt builder."""
    builders = {
        TaskType.READ_PAGE: _build_read_page,
        TaskType.FILL_FORM: _build_fill_form,
        TaskType.NAVIGATE: _build_navigate,
        TaskType.CHECKOUT_FLOW: _build_checkout,
        TaskType.SCRAPE: _build_scrape,
    }
    builder = builders.get(task_type, _build_read_page)
    return builder(
        target_url=target_url,
        user_message=user_message,
        profile=profile,
        page_context=page_context,
    )


# ── Individual prompt builders ─────────────────────────────

def _build_read_page(
    target_url: str,
    user_message: str,
    profile: UserProfile | None,
    page_context: dict[str, Any] | None,
) -> str:
    return f"""
Task: Read and summarize the current web page.

Target URL: {target_url}

Instructions:
1. Navigate to the URL if not already there.
2. Read the page content carefully.
3. Provide a structured summary: page title, main content sections, key information.
4. If the user asked a specific question, answer it based on the page content.

User message: {user_message or "(no specific question)"}

Page context:
{_format_page_context(page_context)}
""".strip()


def _build_fill_form(
    target_url: str,
    user_message: str,
    profile: UserProfile | None,
    page_context: dict[str, Any] | None,
) -> str:
    return f"""
Task: Fill out the form on the current page using the provided user profile.

Target URL: {target_url}

User Profile:
{_format_profile(profile)}

Instructions:
1. Navigate to the URL if not already there.
2. Identify all form fields on the page.
3. Match each form field to the corresponding profile data.
4. Fill in each field accurately — use exact values from the profile.
5. Do NOT submit the form unless explicitly told to.
6. Report which fields were filled and which could not be matched.

User message: {user_message or "(fill the form with my details)"}

Page context:
{_format_page_context(page_context)}

IMPORTANT:
- Do NOT click submit/send/order buttons unless the user explicitly asks.
- If a field has no matching profile data, leave it empty and report it.
""".strip()


def _build_navigate(
    target_url: str,
    user_message: str,
    profile: UserProfile | None,
    page_context: dict[str, Any] | None,
) -> str:
    return f"""
Task: Navigate to a destination based on the user's instruction.

Starting URL: {target_url}

Instructions:
1. Start at the given URL.
2. Follow the user's navigation instruction below.
3. Click links, menus, buttons, or use search to reach the desired page.
4. Report the final URL and a brief summary of the destination page.

User instruction: {user_message or "(navigate to the target URL)"}

Page context:
{_format_page_context(page_context)}
""".strip()


def _build_checkout(
    target_url: str,
    user_message: str,
    profile: UserProfile | None,
    page_context: dict[str, Any] | None,
) -> str:
    return f"""
Task: Drive the checkout flow up to the review/confirmation page. DO NOT complete the purchase.

Target URL: {target_url}

User Profile:
{_format_profile(profile)}

Instructions:
1. Navigate to the URL if not already there.
2. Proceed through the checkout steps:
   a. Fill in shipping/billing address from the user profile.
   b. Select default/first available shipping option.
   c. Fill in contact details (name, email, phone) from profile.
3. STOP at the order review/confirmation page. DO NOT click "Place Order", "Pay Now", or any final submit button.
4. Report what was filled and the current page state.

User message: {user_message or "(complete checkout up to review page)"}

Page context:
{_format_page_context(page_context)}

CRITICAL SAFETY RULES:
- NEVER click any button that says: Place Order, Pay, Submit Order, Confirm Purchase, Buy Now (final).
- STOP as soon as you reach a page showing order summary/review.
- If you are unsure whether a button will finalize the order, DO NOT click it.
""".strip()


def _build_scrape(
    target_url: str,
    user_message: str,
    profile: UserProfile | None,
    page_context: dict[str, Any] | None,
) -> str:
    return f"""
Task: Scrape structured data from the website.

Target URL: {target_url}

Instructions:
1. Navigate to the URL.
2. Collect the requested data based on the user's message.
3. Return data in the structured output schema.
4. Ensure URLs are absolute. No duplicate entries.

User message: {user_message or "(scrape product data from the page)"}

Page context:
{_format_page_context(page_context)}

Quality rules:
- Keep values factual from the page only.
- No duplicate URLs.
- URLs must be absolute.
""".strip()
