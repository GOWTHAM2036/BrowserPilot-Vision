"""Comprehensive integration tests for FastAPI backend and Gradio UI helpers in BrowserPilot Vision."""

import threading
import time
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.llm import LocalLLMClient
from app.main import (
    app as fastapi_app,
    active_task_lock,
    tasks_lock,
    tasks_store,
    _store_task,
    _sanitize_task_response,
)
import app.main as main_module
from app.schemas import (
    ActionDecision,
    ActionType,
    TaskRequest,
    TaskResponse,
    TaskStatus,
    TaskStepRecord,
)
from ui import format_action_history, get_backend_health, cancel_active_task


@pytest.fixture
def api_client():
    """FastAPI TestClient fixture."""
    return TestClient(fastapi_app)


def test_get_health_endpoint(api_client):
    """GET /health must report safe status and non-sensitive configuration."""
    response = api_client.get("/health")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    assert "timestamp" in data
    assert "ollama_connected" in data
    assert data["default_model"] == settings.default_model
    assert data["context_size"] == settings.context_size
    assert data["max_agent_steps"] == settings.max_agent_steps
    assert data["request_timeout"] == settings.request_timeout
    assert isinstance(data["allowed_hosts"], list)
    assert data["task_in_progress"] is False
    assert data["active_task_id"] is None


def test_get_models_endpoint(api_client):
    """GET /models must report configured and installed models without auto-downloading."""
    response = api_client.get("/models")
    assert response.status_code == 200
    data = response.json()

    assert data["default_model"] == settings.default_model
    assert isinstance(data["supported_models"], list)
    assert isinstance(data["installed_models"], list)
    assert "ollama_reachable" in data


def test_post_tasks_validation_empty_and_short(api_client):
    """POST /tasks must reject empty or whitespace-only tasks and URLs."""
    # 1. Empty task
    res_empty_task = api_client.post(
        "/tasks",
        json={"task": "   ", "start_url": "http://127.0.0.1:5000"},
    )
    assert res_empty_task.status_code in (400, 422)

    # 2. Too short task (< 3 chars)
    res_short_task = api_client.post(
        "/tasks",
        json={"task": "hi", "start_url": "http://127.0.0.1:5000"},
    )
    assert res_short_task.status_code in (400, 422)

    # 3. Dangerous / code injection attempt in task
    res_inject_task = api_client.post(
        "/tasks",
        json={"task": "eval('hack()')", "start_url": "http://127.0.0.1:5000"},
    )
    assert res_inject_task.status_code in (400, 422)


def test_post_tasks_safety_url_rejections(api_client):
    """POST /tasks must reject prohibited schemes and disallowed cross-host URLs."""
    # 1. Prohibited scheme: javascript:
    res_js = api_client.post(
        "/tasks",
        json={"task": "Open script", "start_url": "javascript:alert(1)"},
    )
    assert res_js.status_code in (400, 422)

    # 2. Prohibited scheme: file://
    res_file = api_client.post(
        "/tasks",
        json={"task": "Read local file", "start_url": "file:///etc/passwd"},
    )
    assert res_file.status_code == 400
    assert "Invalid or prohibited starting URL" in res_file.json()["detail"]

    # 3. Disallowed external host (whitelisting enforcement)
    res_disallowed = api_client.post(
        "/tasks",
        json={"task": "Scrape external", "start_url": "http://unauthorized-domain.com/"},
    )
    assert res_disallowed.status_code == 400
    assert "not in the allowed hosts list" in res_disallowed.json()["detail"]


def test_post_tasks_ollama_unavailable_returns_503(api_client):
    """POST /tasks must return 503 Service Unavailable when Ollama is unreachable."""
    with patch.object(main_module.llm_client, "is_available", return_value=False):
        res = api_client.post(
            "/tasks",
            json={"task": "Valid task", "start_url": "http://127.0.0.1:5000"},
        )
        assert res.status_code == 503
        assert "Ollama service is currently unreachable" in res.json()["detail"]


def test_post_tasks_concurrency_conflict(api_client):
    """POST /tasks must reject submissions with 409 Conflict if another task is active."""
    with active_task_lock:
        main_module.current_active_task_id = "task_already_running_123"

    try:
        res = api_client.post(
            "/tasks",
            json={"task": "Valid new task", "start_url": "http://127.0.0.1:5000"},
        )
        assert res.status_code == 409
        assert "Only one active task allowed" in res.json()["detail"]
    finally:
        with active_task_lock:
            main_module.current_active_task_id = None


def test_get_task_not_found(api_client):
    """GET /tasks/{task_id} must return 404 for unknown task ID."""
    res = api_client.get("/tasks/non_existent_task_999")
    assert res.status_code == 404
    assert "Task 'non_existent_task_999' not found" in res.json()["detail"]


def test_cancel_task_not_found(api_client):
    """POST /tasks/{task_id}/cancel must return 404 for non-existent task."""
    res = api_client.post("/tasks/non_existent_task_999/cancel")
    assert res.status_code == 404
    assert "Task 'non_existent_task_999' not found to cancel" in res.json()["detail"]


def test_task_response_sanitizes_credentials(api_client):
    """Sensitive values like bearer tokens, passwords, and cards must be masked in task responses."""
    test_id = "task_test_sanitize_1"
    raw_step = TaskStepRecord(
        step=1,
        timestamp="2026-10-26T12:00:00Z",
        thought="Logging in with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 token",
        action="fill",
        target="#password-input",
        value="SecretPassword123!",
        url="http://127.0.0.1:5000/login",
        success=True,
        verification_passed=True,
        message="Entered Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 successfully",
    )

    test_task = TaskResponse(
        task_id=test_id,
        status=TaskStatus.COMPLETED,
        task="Test login",
        start_url="http://127.0.0.1:5000",
        model=settings.default_model,
        result="Logged in with token Bearer abcdef1234567890",
        created_at="2026-10-26T12:00:00Z",
        updated_at="2026-10-26T12:00:05Z",
        history=[raw_step],
    )
    _store_task(test_task)

    res = api_client.get(f"/tasks/{test_id}")
    assert res.status_code == 200
    data = res.json()

    # Verify masking
    assert "[MASKED_TOKEN]" in data["result"]
    assert "Bearer abcdef1234567890" not in data["result"]

    step_data = data["history"][0]
    assert "[MASKED_TOKEN]" in step_data["thought"]
    assert "[MASKED_TOKEN]" in step_data["message"]
    assert "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in step_data["thought"]


def test_ui_history_formatter():
    """Test format_action_history generates clean readable markdown."""
    history = [
        {
            "step": 1,
            "action": "fill",
            "target": "#search-input",
            "value": "chromebook",
            "success": True,
            "thought": "Typing query into search input",
            "message": "Filled query",
        },
        {
            "step": 2,
            "action": "click",
            "target": "#search-btn",
            "success": True,
            "thought": "Submitting search form",
            "message": "Clicked button",
        },
        {
            "step": 3,
            "action": "finish",
            "success": True,
            "verification_passed": True,
            "thought": "Found cheapest laptop",
            "message": "Task complete",
            "evidence": "StudentLite Chromebook 11 - $249",
        },
    ]

    formatted = format_action_history(history)
    assert "#### Step 1: FILL `target='#search-input'` `value='chromebook'` ✅" in formatted
    assert "Typing query into search input" in formatted
    assert "#### Step 2: CLICK `target='#search-btn'` ✅" in formatted
    assert "#### Step 3: FINISH ✅" in formatted
    assert "Verified with observable page evidence" in formatted
    assert "StudentLite Chromebook 11 - $249" in formatted


def test_ui_cancel_active_task_helper():
    """Test cancel_active_task helper with empty and populated task IDs."""
    assert cancel_active_task("") == "No active task ID provided to cancel."
    assert cancel_active_task("   ") == "No active task ID provided to cancel."


def test_ui_get_backend_health_helper():
    """Test get_backend_health helper reports status correctly when FastAPI backend is mocked."""
    status_md, models, default_m = get_backend_health()
    # It should return valid string and model lists
    assert isinstance(status_md, str)
    assert isinstance(models, list)
    assert default_m == settings.default_model


def test_api_task_submission_and_polling_lifecycle(api_client, local_demo_server):
    """Test full asynchronous task creation, polling, and verified completion over FastAPI."""
    finish_decision = ActionDecision(
        thought="Task is complete, reporting StudentLite Chromebook 11",
        action=ActionType.FINISH,
        answer="Cheapest laptop is StudentLite Chromebook 11 for $249",
        evidence="StudentLite Chromebook 11 $249",
    )

    with patch.object(main_module.llm_client, "is_available", return_value=True), \
         patch.object(main_module.llm_client, "decide_action", return_value=finish_decision):

        post_res = api_client.post(
            "/tasks",
            json={
                "task": "Find cheapest laptop on store",
                "start_url": local_demo_server,
                "max_steps": 3,
            },
        )
        assert post_res.status_code == 202
        task_id = post_res.json()["task_id"]
        assert task_id.startswith("task_")

        # Poll task until completion
        final_data = None
        for _ in range(25):
            time.sleep(0.3)
            get_res = api_client.get(f"/tasks/{task_id}")
            assert get_res.status_code == 200
            data = get_res.json()
            if data["status"] in ("completed", "failed", "unverified", "step_limit_reached"):
                final_data = data
                break

        assert final_data is not None, "Task did not reach a terminal state within timeout"
        assert final_data["status"] == "completed"
        assert "StudentLite Chromebook 11" in final_data["result"]
        assert final_data["steps_taken"] >= 1
        assert len(final_data["history"]) >= 1
        assert final_data["history"][-1]["verification_passed"] is True


def test_api_cancellation_lifecycle(api_client, local_demo_server):
    """Test cancelling a task through POST /tasks/{task_id}/cancel while it is executing."""
    wait_decision = ActionDecision(
        thought="Waiting for page to settle",
        action=ActionType.WAIT,
        seconds=1.0,
    )

    with patch.object(main_module.llm_client, "is_available", return_value=True), \
         patch.object(main_module.llm_client, "decide_action", return_value=wait_decision):

        post_res = api_client.post(
            "/tasks",
            json={
                "task": "Long wait task to cancel",
                "start_url": local_demo_server,
                "max_steps": 10,
            },
        )
        assert post_res.status_code == 202
        task_id = post_res.json()["task_id"]

        # Allow worker thread to start
        time.sleep(0.4)

        # Send cancellation request
        cancel_res = api_client.post(f"/tasks/{task_id}/cancel")
        assert cancel_res.status_code == 200

        # Poll until status is cancelled
        final_status = None
        for _ in range(20):
            time.sleep(0.3)
            get_res = api_client.get(f"/tasks/{task_id}")
            if get_res.json()["status"] == "cancelled":
                final_status = "cancelled"
                break

        assert final_status == "cancelled"

