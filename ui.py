"""Gradio user interface for BrowserPilot Vision connected to the FastAPI backend."""

from __future__ import annotations

import os
import time
from typing import Generator, List, Tuple
import gradio as gr
import httpx

from app.config import settings


# Configurable FastAPI backend base URL
BACKEND_URL = os.environ.get("BROWSERPILOT_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")


def get_backend_health() -> Tuple[str, List[str], str]:
    """Query FastAPI backend for service health and available Ollama models."""
    try:
        with httpx.Client(timeout=3.0) as client:
            res_health = client.get(f"{BACKEND_URL}/health")
            res_models = client.get(f"{BACKEND_URL}/models")

            if res_health.status_code == 200 and res_models.status_code == 200:
                health_data = res_health.json()
                models_data = res_models.json()

                ollama_status = "🟢 Connected" if health_data.get("ollama_connected") else "🔴 Disconnected"
                active_task = health_data.get("active_task_id") or "None (Idle)"
                default_m = health_data.get("default_model", settings.default_model)

                installed = models_data.get("installed_models", [])
                choices = installed if installed else settings.supported_models

                status_md = (
                    f"**Backend Status**: 🟢 Online (`{BACKEND_URL}`) | "
                    f"**Ollama**: {ollama_status} | "
                    f"**Default Model**: `{default_m}` | "
                    f"**Active Task**: `{active_task}`"
                )
                return status_md, choices, default_m
    except Exception as e:
        status_md = (
            f"**Backend Status**: 🔴 Unreachable at `{BACKEND_URL}` | "
            f"Please run `uvicorn app.main:app --port 8000` to start the backend."
        )
        return status_md, settings.supported_models, settings.default_model

    return "Backend status unknown", settings.supported_models, settings.default_model


def format_action_history(history: List[dict]) -> str:
    """Format step-by-step action history into readable markdown."""
    if not history:
        return "*Waiting for initial action...*"

    lines = []
    for item in history:
        step = item.get("step", 0)
        action = str(item.get("action", "")).upper()
        target = item.get("target")
        val = item.get("value")
        success = item.get("success", False)
        verified = item.get("verification_passed", False)
        thought = item.get("thought", "")
        msg = item.get("message", "")
        evidence = item.get("evidence")

        icon = "✅" if success else "❌"
        target_info = f" `target='{target}'`" if target else ""
        val_info = f" `value='{val}'`" if val else ""

        entry = [
            f"#### Step {step}: {action}{target_info}{val_info} {icon}",
            f"- **Thought**: {thought}",
            f"- **Execution**: {msg}",
        ]
        if verified:
            entry.append("- **Verification**: Verified with observable page evidence")
        if evidence:
            entry.append(f"- **Evidence**: `{evidence}`")

        lines.append("\n".join(entry))

    return "\n\n---\n\n".join(lines)


def run_task_stream(
    task_desc: str,
    start_url: str,
    selected_model: str,
    max_steps: int,
    use_vision: bool,
) -> Generator[Tuple[str, str, str, str, str, str, str], None, None]:
    """Submit a task to the FastAPI backend and poll for updates until completion.

    Yields:
        (task_id, status, step_progress, history_md, result, evidence, error)
    """
    clean_task = (task_desc or "").strip()
    clean_url = (start_url or "").strip()

    if not clean_task:
        yield "", "ERROR", "Step 0 / 0", "*No actions*", "", "", "Task description cannot be empty."
        return

    if not clean_url:
        yield "", "ERROR", "Step 0 / 0", "*No actions*", "", "", "Starting URL cannot be empty."
        return

    payload = {
        "task": clean_task,
        "start_url": clean_url,
        "model": selected_model,
        "max_steps": int(max_steps),
        "use_vision": bool(use_vision),
    }

    # 1. Submit task to FastAPI backend
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(f"{BACKEND_URL}/tasks", json=payload)
    except httpx.ConnectError:
        err = f"Failed to connect to BrowserPilot backend at {BACKEND_URL}. Ensure the server is running."
        yield "", "BACKEND_UNREACHABLE", "Step 0 / 0", "*No actions*", "", "", err
        return
    except Exception as e:
        yield "", "ERROR", "Step 0 / 0", "*No actions*", "", "", f"Submission error: {str(e)}"
        return

    if resp.status_code == 409:
        err_msg = resp.json().get("detail", "Another task is already running.")
        yield "", "CONFLICT (409)", "Step 0 / 0", "*No actions*", "", "", err_msg
        return

    if resp.status_code == 400:
        err_msg = resp.json().get("detail", "Invalid input or disallowed start URL.")
        yield "", "INVALID_INPUT (400)", "Step 0 / 0", "*No actions*", "", "", err_msg
        return

    if resp.status_code == 503:
        err_msg = resp.json().get("detail", "Ollama service is unreachable.")
        yield "", "SERVICE_UNAVAILABLE (503)", "Step 0 / 0", "*No actions*", "", "", err_msg
        return

    if resp.status_code != 202:
        err_msg = f"Unexpected response from backend ({resp.status_code}): {resp.text}"
        yield "", "ERROR", "Step 0 / 0", "*No actions*", "", "", err_msg
        return

    task_data = resp.json()
    task_id = task_data.get("task_id", "")
    current_status = task_data.get("status", "running")

    yield (
        task_id,
        current_status.upper(),
        f"Step 0 of {max_steps}",
        "*Task queued and starting browser session...*",
        "",
        "",
        "",
    )

    # 2. Responsible polling loop
    terminal_statuses = {
        "completed",
        "failed",
        "unverified",
        "blocked",
        "step_limit_reached",
        "cancelled",
    }

    poll_interval = 0.6
    max_poll_seconds = int(max_steps) * 45  # Cap maximum polling duration
    start_time = time.time()

    with httpx.Client(timeout=10.0) as client:
        while time.time() - start_time < max_poll_seconds:
            time.sleep(poll_interval)
            try:
                poll_resp = client.get(f"{BACKEND_URL}/tasks/{task_id}")
                if poll_resp.status_code != 200:
                    continue
                data = poll_resp.json()
            except Exception:
                continue

            status = data.get("status", "running")
            steps_taken = data.get("steps_taken", 0)
            history = data.get("history", [])
            result = data.get("result") or ""
            evidence = data.get("evidence") or ""
            error = data.get("error") or ""

            history_md = format_action_history(history)
            step_progress = f"Step {steps_taken} of {max_steps}"

            yield (
                task_id,
                status.upper(),
                step_progress,
                history_md,
                result,
                evidence,
                error,
            )

            if status.lower() in terminal_statuses:
                break


def cancel_active_task(task_id: str) -> str:
    """Send cancellation request for the active task to the FastAPI backend."""
    clean_id = (task_id or "").strip()
    if not clean_id:
        return "No active task ID provided to cancel."

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(f"{BACKEND_URL}/tasks/{clean_id}/cancel")
            if resp.status_code == 200:
                return f"Cancellation requested for task '{clean_id}'."
            elif resp.status_code == 404:
                return f"Task '{clean_id}' was not found on the backend."
            else:
                return f"Backend responded with {resp.status_code}: {resp.text}"
    except Exception as e:
        return f"Error contacting backend to cancel task: {e}"


def create_ui() -> gr.Blocks:
    """Build and configure the BrowserPilot Vision Gradio Blocks interface."""
    initial_health_md, initial_models, initial_default_model = get_backend_health()

    custom_css = """
    .safety-banner {
        background-color: #fff3cd;
        border-left: 6px solid #ffc107;
        padding: 12px 16px;
        margin-bottom: 16px;
        border-radius: 4px;
        color: #856404;
    }
    .status-panel {
        font-family: monospace;
    }
    """

    with gr.Blocks(title="BrowserPilot Vision") as demo:
        gr.Markdown(
            """# 🌐 BrowserPilot Vision
**Local-first AI Browser Automation Agent** powered by **Ollama**, **Playwright**, and **FastAPI**.
"""
        )

        health_indicator = gr.Markdown(value=initial_health_md)

        gr.Markdown(
            """
<div class="safety-banner">
<strong>🛡️ Safety Policy Notice:</strong> BrowserPilot Vision enforces local-only execution and host whitelisting (default: <code>localhost</code>, <code>127.0.0.1</code>). Consequential actions (such as submitting financial transactions, making purchases, deleting accounts, or sending messages) are strictly prohibited and require explicit human confirmation. Arbitrary code execution is blocked.
</div>
"""
        )

        with gr.Row():
            with gr.Column(scale=5):
                gr.Markdown("### 🎯 Task Configuration")
                task_input = gr.Textbox(
                    label="Task Description",
                    placeholder="e.g. Find the cheapest laptop and report its name and price",
                    value="Find the cheapest laptop and report its name and price",
                    lines=3,
                )
                url_input = gr.Textbox(
                    label="Starting URL",
                    placeholder="http://127.0.0.1:5000/",
                    value="http://127.0.0.1:5000/",
                )

                with gr.Row():
                    model_dropdown = gr.Dropdown(
                        label="Ollama Model",
                        choices=initial_models,
                        value=initial_default_model,
                    )
                    max_steps_slider = gr.Slider(
                        label="Maximum Steps",
                        minimum=3,
                        maximum=25,
                        value=settings.max_agent_steps,
                        step=1,
                    )

                vision_checkbox = gr.Checkbox(
                    label="Enable Vision Fallback (analyze screenshot on failure)",
                    value=False,
                )

                with gr.Row():
                    run_btn = gr.Button("🚀 Run Task", variant="primary", scale=2)
                    cancel_btn = gr.Button("⏹️ Cancel Task", variant="stop", scale=1)

            with gr.Column(scale=6):
                gr.Markdown("### 📊 Execution Monitor")
                with gr.Row():
                    task_id_display = gr.Textbox(
                        label="Active Task ID",
                        value="",
                        interactive=False,
                        scale=2,
                    )
                    status_display = gr.Textbox(
                        label="Task Status",
                        value="IDLE",
                        interactive=False,
                        scale=1,
                    )
                    step_display = gr.Textbox(
                        label="Step Progress",
                        value="Step 0 / 0",
                        interactive=False,
                        scale=1,
                    )

                result_display = gr.Textbox(
                    label="Verified Final Result / Answer",
                    placeholder="Verified answer will be displayed upon successful completion...",
                    lines=2,
                    interactive=False,
                )
                evidence_display = gr.Textbox(
                    label="Observable Browser Evidence",
                    placeholder="Observable page evidence confirming the task...",
                    lines=2,
                    interactive=False,
                )
                error_display = gr.Textbox(
                    label="Errors & Safety Alerts",
                    placeholder="Any safety interventions or error messages will appear here...",
                    lines=2,
                    interactive=False,
                )

        gr.Markdown("### 📜 Action History & Reasoning")
        history_display = gr.Markdown(value="*No actions executed yet.*")

        # Wire Run Task
        run_btn.click(
            fn=run_task_stream,
            inputs=[task_input, url_input, model_dropdown, max_steps_slider, vision_checkbox],
            outputs=[
                task_id_display,
                status_display,
                step_display,
                history_display,
                result_display,
                evidence_display,
                error_display,
            ],
        )

        # Wire Cancel Task
        cancel_btn.click(
            fn=cancel_active_task,
            inputs=[task_id_display],
            outputs=[error_display],
        )

    return demo


if __name__ == "__main__":
    ui = create_ui()
    ui.launch(server_name="127.0.0.1", server_port=7860, share=False)
