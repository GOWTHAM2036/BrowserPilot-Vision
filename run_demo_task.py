"""Script to execute a live browsing task against the local demo website using Ollama."""

import sys
import threading
import time
from werkzeug.serving import make_server

from app.agent import BrowserAgent
from app.config import settings
from demo_site.app import app as demo_app
from app.schemas import TaskRequest


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=== Starting Local Demo Shopping Site ===")
    server = make_server("127.0.0.1", 5000, demo_app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(1.0)
    print("Demo site running at http://127.0.0.1:5000/")

    default_task = "Locate the StudentLite Chromebook 11, add it to the cart, and verify the cart content."
    task_desc = sys.argv[1] if len(sys.argv) > 1 else default_task
    print(f"\n=== Running Live BrowserPilot Task: '{task_desc}' ===")
    print(f"Model: {settings.default_model}")

    def on_step(record):
        print(f"\n[STEP {record.step}] Action: {record.action.upper()} | Success: {record.success}")
        print(f"  Thought: {record.thought}")
        if record.target:
            print(f"  Target: {record.target}")
        if record.value:
            print(f"  Value: {record.value}")
        print(f"  Outcome: {record.message}")
        if record.evidence:
            print(f"  Evidence: {record.evidence}")

    agent = BrowserAgent(step_callback=on_step, headless=True)
    req = TaskRequest(
        task=task_desc,
        start_url="http://127.0.0.1:5000/",
        model=settings.default_model,
        max_steps=10,
    )

    start_time = time.time()
    response = agent.run_task(req)
    duration = time.time() - start_time

    print("\n" + "=" * 50)
    print(f"Task Status : {response.status.value.upper()}")
    print(f"Steps Taken : {response.steps_taken}")
    print(f"Duration    : {duration:.2f} seconds")
    print(f"Result      : {response.result}")
    print(f"Evidence    : {response.evidence}")
    if response.error:
        print(f"Error       : {response.error}")
    print("=" * 50)

    server.shutdown()
    return 0 if response.status.value == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
