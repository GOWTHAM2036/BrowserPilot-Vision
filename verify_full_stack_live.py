"""Full-stack live end-to-end verification script for BrowserPilot Vision.

Tests the complete flow:
  Client/UI -> FastAPI HTTP API (:8000) -> Worker Thread -> Local Ollama (gemma3:4b) -> Playwright -> Demo Site (:5000) -> Verification -> UI Formatter.
"""

import sys
import threading
import time
import httpx
import uvicorn
from werkzeug.serving import make_server

from app.main import app as fastapi_app
from demo_site.app import app as demo_flask_app, CART_ITEMS
from ui import format_action_history


def run_full_stack_test():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 60)
    print("BROWSERPILOT VISION: FULL-STACK LIVE VERIFICATION")
    print("=" * 60)

    # 1. Start Demo Store on 127.0.0.1:5000
    print("\n[1/6] Launching Local Demo Store on http://127.0.0.1:5000...")
    CART_ITEMS.clear()
    demo_server = make_server("127.0.0.1", 5000, demo_flask_app)
    demo_thread = threading.Thread(target=demo_server.serve_forever, daemon=True)
    demo_thread.start()
    time.sleep(1.0)
    print("  -> Demo Store started successfully.")

    # 2. Start FastAPI server on 127.0.0.1:8000
    print("\n[2/6] Launching FastAPI Backend on http://127.0.0.1:8000...")
    config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=8000, log_level="warning")
    api_server = uvicorn.Server(config)
    api_thread = threading.Thread(target=api_server.run, daemon=True)
    api_thread.start()
    time.sleep(1.5)
    print("  -> FastAPI Backend started successfully.")

    # 3. Test Health & Models endpoint
    print("\n[3/6] Verifying Backend Health & Ollama reachability...")
    with httpx.Client(timeout=10.0) as client:
        res_health = client.get("http://127.0.0.1:8000/health")
        assert res_health.status_code == 200, f"Health check failed: {res_health.status_code}"
        health_data = res_health.json()
        print(f"  -> Health OK: ollama_connected={health_data['ollama_connected']}, default_model={health_data['default_model']}")
        assert health_data["ollama_connected"] is True, "Ollama must be running for live verification!"

        res_models = client.get("http://127.0.0.1:8000/models")
        assert res_models.status_code == 200
        models_data = res_models.json()
        print(f"  -> Installed Ollama Models: {models_data.get('installed_models', [])}")

    # 4. Submit Task via POST /tasks
    print("\n[4/6] Submitting Task via FastAPI POST /tasks...")
    task_payload = {
        "task": "Locate the StudentLite Chromebook 11, add it to the cart, and verify the cart content.",
        "start_url": "http://127.0.0.1:5000/",
        "model": "gemma3:4b",
        "max_steps": 10,
        "use_vision": False,
    }

    with httpx.Client(timeout=10.0) as client:
        submit_res = client.post("http://127.0.0.1:8000/tasks", json=task_payload)
        assert submit_res.status_code == 202, f"Task submission failed: {submit_res.status_code} - {submit_res.text}"
        init_data = submit_res.json()
        task_id = init_data["task_id"]
        print(f"  -> Task Accepted! Assigned Task ID: {task_id}")
        assert init_data["status"] == "running"

    # 5. Poll GET /tasks/{task_id} (Responsible Polling Loop)
    print("\n[5/6] Polling Task Execution (Simulating UI Poller)...")
    start_time = time.time()
    last_step = 0
    final_data = None

    with httpx.Client(timeout=10.0) as client:
        for _ in range(60):  # Poll up to 60s
            time.sleep(0.6)
            poll_res = client.get(f"http://127.0.0.1:8000/tasks/{task_id}")
            if poll_res.status_code != 200:
                continue
            data = poll_res.json()
            status = data.get("status")
            steps = data.get("steps_taken", 0)

            if steps > last_step:
                last_step = steps
                latest_step = data["history"][-1] if data.get("history") else None
                act = latest_step.get("action") if latest_step else "unknown"
                th = latest_step.get("thought", "")[:70] if latest_step else ""
                print(f"  [Progress] Step {steps}/10 | Action: {act.upper()} | Thought: {th}...")

            if status in ("completed", "failed", "unverified", "step_limit_reached", "cancelled"):
                final_data = data
                break

    duration = time.time() - start_time
    assert final_data is not None, "Task did not reach a terminal state within timeout"

    print("\n" + "=" * 60)
    print(f"EXECUTION SUMMARY:")
    print(f"Task ID      : {final_data['task_id']}")
    print(f"Final Status : {final_data['status'].upper()}")
    print(f"Steps Taken  : {final_data['steps_taken']}")
    print(f"Duration     : {duration:.2f}s")
    print(f"Result       : {final_data.get('result')}")
    print(f"Evidence     : {final_data.get('evidence')}")
    print("=" * 60)

    assert final_data["status"] == "completed", f"Task failed with status: {final_data['status']} - Error: {final_data.get('error')}"
    assert "StudentLite Chromebook 11" in str(final_data.get("result", ""))
    assert final_data.get("evidence") is not None

    # 6. Verify Gradio UI formatting
    print("\n[6/6] Verifying Gradio UI Action History Rendering...")
    formatted_md = format_action_history(final_data["history"])
    print(f"  -> Formatted Markdown length: {len(formatted_md)} chars")
    assert "✅" in formatted_md, "UI Formatter must include success indicators"
    assert "Verified with observable page evidence" in formatted_md

    # Independent Cart State Check
    with httpx.Client(timeout=5.0) as client:
        cart_page = client.get("http://127.0.0.1:5000/cart")
        assert "StudentLite Chromebook 11" in cart_page.text
        assert "$199.00" in cart_page.text
        print("  -> Independent Cart Verification: Confirmed StudentLite Chromebook 11 present in cart!")

    # Teardown
    demo_server.shutdown()
    api_server.should_exit = True
    print("\n>>> FULL-STACK LIVE VERIFICATION PASSED PERFECTLY! <<<")
    return 0


if __name__ == "__main__":
    sys.exit(run_full_stack_test())
