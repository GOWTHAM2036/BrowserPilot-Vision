"""Capture authentic screenshots of the real demo site and UI for submission evidence."""

import sys
import threading
import time
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from demo_site.app import app as demo_app, CART_ITEMS, PRODUCTS
from ui import create_ui


def capture_evidence():
    print("=== Capturing Genuine Demo Screenshots ===")

    # 1. Start Demo Store on 5000
    demo_server = make_server("127.0.0.1", 5000, demo_app)
    demo_thread = threading.Thread(target=demo_server.serve_forever, daemon=True)
    demo_thread.start()
    time.sleep(1.0)

    # 2. Start Gradio UI on 7860
    ui_blocks = create_ui()
    ui_thread = threading.Thread(
        target=lambda: ui_blocks.launch(server_name="127.0.0.1", server_port=7860, share=False, prevent_thread_lock=True),
        daemon=True,
    )
    ui_thread.start()
    time.sleep(2.0)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # A. Capture Demo Store Catalog
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto("http://127.0.0.1:5000/")
        page.wait_for_selector(".product-grid")
        page.screenshot(path="assets/demo_site_catalog.png", full_page=False)
        print("  -> Saved: assets/demo_site_catalog.png")

        # B. Add StudentLite Chromebook 11 to cart and capture verified cart state
        page.goto("http://127.0.0.1:5000/cart/add/1")
        page.wait_for_selector("#cart-table")
        page.screenshot(path="assets/demo_site_cart_verified.png", full_page=False)
        print("  -> Saved: assets/demo_site_cart_verified.png")

        # C. Capture Gradio UI Interface
        page.goto("http://127.0.0.1:7860/")
        page.wait_for_selector(".safety-banner")
        time.sleep(1.0)
        page.screenshot(path="assets/gradio_ui_interface.png", full_page=False)
        print("  -> Saved: assets/gradio_ui_interface.png")

        browser.close()

    demo_server.shutdown()
    ui_blocks.close()
    print("=== Evidence Capture Completed Successfully ===")


if __name__ == "__main__":
    capture_evidence()
