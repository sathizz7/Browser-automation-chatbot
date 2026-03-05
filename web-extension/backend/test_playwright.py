"""
Phase 5 — Verification Test Script

Tests both Headless API mode and CDP mode end-to-end.

Usage:
    cd backend
    python test_playwright.py              # Tests headless mode
    python test_playwright.py --cdp        # Tests CDP mode (Chrome must be running with --remote-debugging-port=9222)
    python test_playwright.py --all        # Tests both modes
"""

import asyncio
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("test")


async def test_headless():
    """Test 1: Headless mode — launch browser, navigate, scrape, act."""
    from browser.manager import BrowserManager, BrowserConfig
    from browser.scraper import scrape_page, format_elements_for_llm
    from browser import action_handler

    print("\n" + "=" * 60)
    print("  TEST 1: HEADLESS MODE")
    print("=" * 60)

    manager = BrowserManager(BrowserConfig(headless=True))
    errors = []

    try:
        # 1. Launch
        print("\n🚀 Launching headless browser...")
        page = await manager.launch_headless()
        assert manager.is_connected, "Browser should be connected"
        assert manager.mode == "headless", f"Mode should be headless, got {manager.mode}"
        print("   ✅ Browser launched")

        # 2. Navigate
        print("\n🌐 Navigating to Google...")
        result = await manager.navigate("https://www.google.com")
        assert result["success"], f"Navigation failed: {result}"
        assert "google" in result["url"].lower(), f"URL should contain google: {result['url']}"
        print(f"   ✅ Navigated to: {result['title']} ({result['url']})")

        # 3. Scrape
        print("\n📸 Scraping page...")
        scraped = await scrape_page(page, take_screenshot=True)
        assert scraped.url, "URL should not be empty"
        assert scraped.element_count > 0, "Should find some elements"
        assert scraped.screenshot_base64, "Screenshot should be captured"
        print(f"   ✅ Scraped {scraped.element_count} elements")
        print(f"   ✅ Screenshot: {len(scraped.screenshot_base64)} chars (base64)")

        # 4. Format for LLM
        print("\n📋 Formatting for LLM...")
        llm_text = format_elements_for_llm(scraped)
        assert len(llm_text) > 0, "LLM text should not be empty"
        print(f"   ✅ LLM text ({len(llm_text)} chars):")
        for line in llm_text.split("\n")[:5]:
            print(f"      {line}")
        if scraped.element_count > 5:
            print(f"      ... +{scraped.element_count - 5} more")

        # 5. Action: type into search
        print("\n⌨️ Typing 'hello world' into search box...")
        # Find the search input ref
        search_input = None
        for el in scraped.elements:
            if el.tag == "input" and el.type == "text":
                search_input = el.ref
                break
            if el.tag == "textarea":
                search_input = el.ref
                break

        if search_input:
            result = await action_handler.type_text(page, search_input, "hello world")
            if result["success"]:
                print(f"   ✅ Typed into {search_input}")
            else:
                print(f"   ⚠️ Type failed: {result.get('error')}")
                errors.append(f"Type failed: {result.get('error')}")
        else:
            print("   ⚠️ No search input found (skipping type test)")

        # 6. Scroll
        print("\n📜 Scrolling down...")
        result = await action_handler.scroll(page, "down", 300)
        assert result["success"], f"Scroll failed: {result}"
        print("   ✅ Scrolled down 300px")

        # 7. Screenshot after actions
        print("\n📸 Taking screenshot after actions...")
        screenshot = await manager.take_screenshot()
        assert len(screenshot) > 0, "Screenshot should have bytes"
        print(f"   ✅ Screenshot: {len(screenshot)} bytes")

    except Exception as e:
        errors.append(f"HEADLESS TEST ERROR: {e}")
        logger.error(f"Test error: {e}", exc_info=True)

    finally:
        await manager.close()
        print(f"\n🔒 Browser closed")

    # Summary
    print("\n" + "-" * 40)
    if errors:
        print(f"❌ HEADLESS TEST: {len(errors)} error(s)")
        for e in errors:
            print(f"   • {e}")
        return False
    else:
        print("✅ HEADLESS TEST PASSED")
        return True


async def test_cdp():
    """Test 2: CDP mode — connect to existing Chrome, scrape, act."""
    from browser.manager import BrowserManager, BrowserConfig
    from browser.scraper import scrape_page, format_elements_for_llm
    from browser import action_handler

    print("\n" + "=" * 60)
    print("  TEST 2: CDP MODE")
    print("  (Chrome must be running with --remote-debugging-port=9222)")
    print("=" * 60)

    manager = BrowserManager(BrowserConfig(cdp_endpoint="http://localhost:9222"))
    errors = []

    try:
        # 1. Connect
        print("\n🔌 Connecting to Chrome via CDP...")
        page = await manager.connect_cdp()
        assert manager.is_connected, "Browser should be connected"
        assert manager.mode == "cdp", f"Mode should be cdp, got {manager.mode}"
        print(f"   ✅ Connected to Chrome — tab: {page.url}")

        # 2. Navigate
        print("\n🌐 Navigating to example.com...")
        result = await action_handler.navigate(page, "https://www.example.com")
        assert result["success"], f"Navigate failed: {result}"
        print(f"   ✅ Navigated to: {result.get('title')} ({result.get('url')})")

        # 3. Scrape
        print("\n📸 Scraping page...")
        scraped = await scrape_page(page, take_screenshot=True)
        assert scraped.url, "URL should not be empty"
        print(f"   ✅ Scraped {scraped.element_count} elements from {scraped.url}")

        # 4. Format
        llm_text = format_elements_for_llm(scraped)
        print(f"   ✅ LLM text ({len(llm_text)} chars)")

        # 5. Navigate to Google and search
        print("\n🌐 Navigating to Google...")
        result = await action_handler.navigate(page, "https://www.google.com")
        print(f"   ✅ Navigated to Google")

        scraped = await scrape_page(page, take_screenshot=False)
        search_input = None
        for el in scraped.elements:
            if el.tag in ("input", "textarea") and el.type in ("text", ""):
                search_input = el.ref
                break
        if search_input:
            print(f"\n⌨️ Typing 'playwright test' into {search_input}...")
            result = await action_handler.type_text(page, search_input, "playwright test")
            print(f"   ✅ Typed into search box" if result["success"] else f"   ⚠️ {result.get('error')}")
        else:
            print("   ⚠️ No search input found")

    except ConnectionRefusedError:
        errors.append(
            "Could not connect to Chrome. Make sure Chrome is running with:\n"
            '   chrome.exe --remote-debugging-port=9222'
        )
    except Exception as e:
        errors.append(f"CDP TEST ERROR: {e}")
        logger.error(f"Test error: {e}", exc_info=True)

    finally:
        await manager.close()
        print(f"\n🔒 Disconnected (Chrome stays open)")

    print("\n" + "-" * 40)
    if errors:
        print(f"❌ CDP TEST: {len(errors)} error(s)")
        for e in errors:
            print(f"   • {e}")
        return False
    else:
        print("✅ CDP TEST PASSED")
        return True


async def main():
    args = set(sys.argv[1:])
    run_headless = "--all" in args or "--headless" in args or not args
    run_cdp = "--all" in args or "--cdp" in args

    results = []

    if run_headless:
        results.append(("Headless", await test_headless()))

    if run_cdp:
        results.append(("CDP", await test_cdp()))

    # Final summary
    print("\n" + "=" * 60)
    print("  FINAL RESULTS")
    print("=" * 60)
    all_passed = True
    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("=" * 60)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
