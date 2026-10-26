"""Tests for page observer, element extraction, and size limits."""

import pytest
from playwright.sync_api import sync_playwright
from app.observer import PageObserver


@pytest.fixture(scope="module")
def browser_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        yield page
        page.close()
        context.close()
        browser.close()


def test_observer_extracts_elements_and_limits_text(browser_page):
    html_content = """<!DOCTYPE html>
    <html>
    <head><title>Test Shopping Page</title></head>
    <body>
        <header>
            <h1>Gadget Depot</h1>
        </header>
        <main>
            <input id="search-box" type="text" placeholder="Search gadgets..." />
            <button id="search-btn">Search</button>
            <a href="/deals" id="deals-link">Hot Deals</a>
            <button style="display:none;" id="hidden-btn">Hidden Secret</button>
            <p id="long-desc">""" + ("Super fast laptop with long battery life. " * 50) + """</p>
        </main>
    </body>
    </html>"""

    browser_page.set_content(html_content)

    observer = PageObserver(max_chars=200)
    obs, target_map = observer.observe(browser_page, capture_screenshot=False)

    assert obs.title == "Test Shopping Page"
    # Verify observation size limit truncation
    assert obs.truncated is True
    assert obs.char_count <= 200

    # Verify interactive targets
    candidate_names = [c.name.lower() for c in obs.interactive_elements]
    assert any("search" in name for name in candidate_names)
    assert any("hot deals" in name for name in candidate_names)

    # Verify hidden element is excluded
    assert not any("hidden secret" in name for name in candidate_names)

    # Verify target lookup map
    assert len(target_map) > 0
    assert "1" in target_map


def test_observer_screenshot_generation(browser_page, tmp_path):
    browser_page.set_content("<html><body><h1>Screenshot Test</h1></body></html>")
    observer = PageObserver()
    screenshot_file = tmp_path / "test_screen.png"
    result_path = observer.take_screenshot(browser_page, filename=str(screenshot_file))

    assert result_path.exists()
    assert result_path.stat().st_size > 0
