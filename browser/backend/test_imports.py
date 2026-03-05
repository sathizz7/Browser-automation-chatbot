"""Quick sanity check — imports + allowlist logic."""
from agent import AgentConfig, ScraperConfig, run_automation, run_scraper
from schemas import TaskType, UserProfile, AutomateRequest, AutomateResult, ScrapeResult
from allowlist import AllowlistManager
from prompts import build_prompt

print("All imports OK")

# Test allowlist
al = AllowlistManager.load()
print(f"Allowlist mode: {al.mode}")
print(f"Blocked domains: {al.blocked_domains}")
print(f"paypal.com allowed? {al.is_allowed('https://www.paypal.com/checkout')}")
print(f"amazon.com allowed? {al.is_allowed('https://amazon.com/some-page')}")
print(f"books.toscrape.com strategy: {al.get_strategy('https://books.toscrape.com/')}")

# Test prompt building
prompt = build_prompt(
    task_type=TaskType.FILL_FORM,
    target_url="https://example.com/form",
    user_message="Fill with my details",
    profile=UserProfile(full_name="Test User", email="test@example.com", phone="9876543210"),
)
print(f"\nGenerated prompt length: {len(prompt)} chars")
print("Prompt preview:")
print(prompt[:300])

# Test schema validation
profile = UserProfile(full_name="Sathish Kumar")
print(f"\nProfile first_name auto-derived: '{profile.first_name}'")
print(f"Profile last_name auto-derived: '{profile.last_name}'")

print("\n✓ All Phase 1 sanity checks passed!")
