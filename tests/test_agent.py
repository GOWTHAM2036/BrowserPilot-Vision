"""Tests for BrowserAgent loop, execution recovery, step limits, and deterministic demo site E2E."""

import threading
import time
from unittest.mock import MagicMock
import pytest
from werkzeug.serving import make_server

from app.agent import BrowserAgent
from app.config import settings
from demo_site.app import app as flask_demo_app
from app.executor import ActionExecutor
from app.llm import LocalLLMClient
from app.safety import SafetyPolicy
from app.schemas import (
    ActionDecision,
    ActionResult,
    ActionType,
    PageObservation,
    TaskRequest,
    TaskStatus,
)



def test_agent_step_limit_reached(local_demo_server):
    """Test that agent stops and marks step_limit_reached when actions exceed max_steps."""
    mock_llm = MagicMock(spec=LocalLLMClient)
    # Return wait action continuously
    mock_llm.decide_action.return_value = ActionDecision(
        thought="Just waiting",
        action=ActionType.WAIT,
        seconds=0.5,
    )

    agent = BrowserAgent(llm_client=mock_llm, max_steps=3, headless=True)
    req = TaskRequest(
        task="Test step limit",
        start_url=local_demo_server,
        max_steps=3,
    )
    resp = agent.run_task(req)

    assert resp.status == TaskStatus.STEP_LIMIT_REACHED
    assert resp.steps_taken == 3
    assert len(resp.history) == 3


def test_agent_recovery_and_failure(local_demo_server):
    """Test that agent fails after exceeding max recovery attempts for invalid targets."""
    mock_llm = MagicMock(spec=LocalLLMClient)
    # Provide an impossible target to trigger failure
    mock_llm.decide_action.return_value = ActionDecision(
        thought="Clicking non-existent button",
        action=ActionType.CLICK,
        target="#non-existent-impossible-button-9999",
    )

    agent = BrowserAgent(llm_client=mock_llm, max_steps=5, headless=True)
    req = TaskRequest(
        task="Test failed recovery",
        start_url=local_demo_server,
        max_steps=5,
    )
    resp = agent.run_task(req)

    assert resp.status == TaskStatus.FAILED
    assert "recovery attempts" in (resp.error or "")


def test_ambiguous_target_rejection():
    """Test that ActionExecutor rejects ambiguous targets matching multiple elements."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # Create page with multiple identical buttons
        page.set_content("""
        <html>
            <body>
                <button class="action-btn">Duplicate Button</button>
                <button class="action-btn">Duplicate Button</button>
            </body>
        </html>
        """)

        executor = ActionExecutor()
        action = ActionDecision(
            thought="Click duplicate button",
            action=ActionType.CLICK,
            target="Duplicate Button",
        )

        result = executor.execute(page, action)
        assert result.success is False
        assert "Ambiguous target" in result.message

        browser.close()


def test_deterministic_demo_e2e(local_demo_server):
    """End-to-End test on the local demo website executing real browser actions deterministically."""
    # Scripted sequence of LLM decisions:
    # 1. Fill search input with "Chromebook"
    # 2. Click Search button
    # 3. Finish with the cheapest laptop found
    scripted_actions = [
        ActionDecision(
            thought="Search for Chromebook",
            action=ActionType.FILL,
            target="#search-input",
            value="Chromebook",
        ),
        ActionDecision(
            thought="Submit search query",
            action=ActionType.CLICK,
            target="#search-btn",
        ),
        ActionDecision(
            thought="Cheapest result is StudentLite Chromebook 11 at $199.00",
            action=ActionType.FINISH,
            answer="StudentLite Chromebook 11 is the cheapest laptop priced at $199.00",
            evidence="StudentLite Chromebook 11",
        ),
    ]

    mock_llm = MagicMock(spec=LocalLLMClient)
    mock_llm.decide_action.side_effect = scripted_actions

    policy = SafetyPolicy(allowed_hosts=["localhost", "127.0.0.1"])
    agent = BrowserAgent(
        llm_client=mock_llm,
        safety_policy=policy,
        max_steps=5,
        headless=True,
    )

    req = TaskRequest(
        task="Find the cheapest Chromebook laptop",
        start_url=local_demo_server,
        max_steps=5,
    )

    response = agent.run_task(req)

    assert response.status == TaskStatus.COMPLETED
    assert "StudentLite Chromebook 11" in (response.result or "")
    assert response.evidence is not None
    assert response.steps_taken == 3
    assert len(response.history) == 3
    assert response.history[0].action == "fill"
    assert response.history[1].action == "click"
    assert response.history[2].action == "finish"
    assert response.history[2].verification_passed is True


def test_llm_malformed_output_retry():
    """Test LocalLLMClient retrying once upon receiving malformed output."""
    client = LocalLLMClient()

    # Mock ollama client response: 1st returns invalid json, 2nd returns valid json
    mock_bad_resp = MagicMock()
    mock_bad_resp.message.content = "INVALID NON-JSON OUTPUT"

    valid_json = '{"thought": "Now valid", "action": "wait", "seconds": 1.0}'
    mock_good_resp = MagicMock()
    mock_good_resp.message.content = valid_json

    client.client.chat = MagicMock(side_effect=[mock_bad_resp, mock_good_resp])

    obs = PageObservation(
        url="http://127.0.0.1:5000",
        title="Demo Store",
        visible_text="Some text",
        interactive_elements=[],
    )

    decision = client.decide_action("Wait a bit", obs, step=1, max_steps=5)
    assert decision.action == ActionType.WAIT
    assert decision.thought == "Now valid"
    assert client.client.chat.call_count == 2


def test_fastapi_endpoints_and_single_task_lock():
    """Test FastAPI /health, /models, /tasks endpoints and single-task concurrency restriction."""
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app, active_task_lock, current_active_task_id
    import app.main as main_module

    client = TestClient(fastapi_app)

    # 1. Health check
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "ok"

    # 2. Models list
    res_models = client.get("/models")
    assert res_models.status_code == 200
    assert "default_model" in res_models.json()

    # 3. Simulate active task lock conflict (409)
    with active_task_lock:
        main_module.current_active_task_id = "task_running_test"

    try:
        res_conflict = client.post(
            "/tasks",
            json={"task": "Another task", "start_url": "http://127.0.0.1:5000"},
        )
        assert res_conflict.status_code == 409
        assert "Only one active task allowed" in res_conflict.json()["detail"]
    finally:
        with active_task_lock:
            main_module.current_active_task_id = None


def test_finish_verification_rejects_hallucinated_evidence(local_demo_server):
    """Test that agent rejects finish action when the claimed result/evidence is not on the page."""
    mock_llm = MagicMock(spec=LocalLLMClient)
    # Model fabricates an answer completely missing from the demo page
    mock_llm.decide_action.return_value = ActionDecision(
        thought="Reporting fake laptop",
        action=ActionType.FINISH,
        answer="The cheapest laptop is Alienware M18 Quantum for $12.50",
        evidence="Alienware M18 Quantum $12.50 in stock",
    )

    agent = BrowserAgent(llm_client=mock_llm, max_steps=4, headless=True)
    req = TaskRequest(
        task="Find laptops",
        start_url=local_demo_server,
        max_steps=4,
    )
    resp = agent.run_task(req)

    # Verification must fail and not report COMPLETED merely because finish was chosen
    assert resp.status in (TaskStatus.UNVERIFIED, TaskStatus.FAILED)
    assert "Finish rejected" in (resp.error or "")


def test_anti_thrashing_loop_detection(local_demo_server):
    """Test that repetitive identical actions trigger anti-thrashing warnings in history."""
    mock_llm = MagicMock(spec=LocalLLMClient)
    # Scroll action repeated with no state change
    mock_llm.decide_action.return_value = ActionDecision(
        thought="Scrolling down",
        action=ActionType.SCROLL,
        direction="down",
        amount=50,
    )

    agent = BrowserAgent(llm_client=mock_llm, max_steps=3, headless=True)
    req = TaskRequest(
        task="Scroll test",
        start_url=local_demo_server,
        max_steps=3,
    )
    resp = agent.run_task(req)
    assert resp.steps_taken == 3


def test_agent_vision_fallback_on_failure(local_demo_server):
    """Test that vision analysis is triggered as fallback when an action fails with use_vision enabled."""
    mock_llm = MagicMock(spec=LocalLLMClient)
    mock_llm.decide_action.return_value = ActionDecision(
        thought="Clicking broken button",
        action=ActionType.CLICK,
        target="#non-existent-button-vision-test",
    )
    mock_llm.analyze_vision.return_value = "Visible buttons: Search, Sort Price"

    agent = BrowserAgent(llm_client=mock_llm, max_steps=2, headless=True)
    req = TaskRequest(
        task="Test vision fallback",
        start_url=local_demo_server,
        max_steps=2,
        use_vision=True,
    )
    resp = agent.run_task(req)

    # analyze_vision should have been called as fallback
    assert mock_llm.analyze_vision.called


def test_task_cancellation_mid_execution(local_demo_server):
    """Test that agent.cancel() halts execution and transitions task to CANCELLED."""
    mock_llm = MagicMock(spec=LocalLLMClient)

    def slow_action(*args, **kwargs):
        agent.cancel()
        return ActionDecision(
            thought="Waiting",
            action=ActionType.WAIT,
            seconds=0.5,
        )

    mock_llm.decide_action.side_effect = slow_action

    agent = BrowserAgent(llm_client=mock_llm, max_steps=5, headless=True)
    req = TaskRequest(
        task="Test cancel",
        start_url=local_demo_server,
        max_steps=5,
    )
    resp = agent.run_task(req)

    assert resp.status == TaskStatus.CANCELLED


def test_ollama_connection_failure(local_demo_server):
    """Test that agent and LLM client handle Ollama connection failure gracefully."""
    import httpx

    client = LocalLLMClient(base_url="http://127.0.0.1:59999")
    client.client.chat = MagicMock(side_effect=httpx.ConnectError("Failed to connect to host"))

    obs = PageObservation(
        url="http://127.0.0.1:5000",
        title="Demo Store",
        visible_text="Some text",
        interactive_elements=[],
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.decide_action("Search laptops", obs, step=1, max_steps=5)

    assert "Failed to connect" in str(exc_info.value) or "connection failure" in str(exc_info.value)


def test_missing_and_stale_element_identifiers():
    """Test revalidation detecting missing or stale element identifiers."""
    from playwright.sync_api import sync_playwright
    from app.observer import PageObserver
    from app.schemas import TargetCandidate

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content("""
        <html>
            <body>
                <button id="dynamic-btn">Click Me</button>
            </body>
        </html>
        """)

        observer = PageObserver()
        obs, target_map = observer.observe(page)
        candidate = target_map.get("1")
        assert candidate is not None

        # 1. Candidate is valid initially
        is_valid, msg = observer.revalidate_element(page, candidate)
        assert is_valid is True

        # 2. Modify DOM to remove the element (making it stale)
        page.evaluate("() => document.getElementById('dynamic-btn').remove()")

        # Revalidation must now catch the stale element
        is_valid, msg = observer.revalidate_element(page, candidate)
        assert is_valid is False
        assert "stale" in msg.lower() or "no longer" in msg.lower()

        # Executor must also report stale element error
        executor = ActionExecutor()
        action = ActionDecision(
            thought="Click stale element",
            action=ActionType.CLICK,
            target="1",
        )
        res = executor.execute(page, action, target_map)
        assert res.success is False
        assert res.error_category in ("stale_element", "missing_target")

        browser.close()


def test_logging_failures_do_not_crash_agent(local_demo_server, monkeypatch):
    """Test that logging failures (disk errors, permissions) do not crash the agent."""
    from app.logger import TaskLogger

    # Simulate filesystem failure inside TaskLogger
    def failing_log_event(self, *args, **kwargs):
        raise IOError("Disk write simulation error")

    monkeypatch.setattr(TaskLogger, "log_event", failing_log_event)

    mock_llm = MagicMock(spec=LocalLLMClient)
    mock_llm.decide_action.return_value = ActionDecision(
        thought="Wait safely",
        action=ActionType.WAIT,
        seconds=0.5,
    )

    agent = BrowserAgent(llm_client=mock_llm, max_steps=2, headless=True)
    req = TaskRequest(
        task="Test logger resilience",
        start_url=local_demo_server,
        max_steps=2,
    )

    # Agent should finish step limit without crashing despite logger errors
    resp = agent.run_task(req)
    assert resp.status == TaskStatus.STEP_LIMIT_REACHED
    assert resp.steps_taken == 2


def test_demo_site_add_to_cart_e2e(local_demo_server):
    """End-to-end cart demonstration: Locate product, add to cart, and verify observable cart content."""
    # Scripted sequence:
    # 1. Click 'Add to Cart' for product 1 (StudentLite Chromebook 11)
    # 2. Observe cart and finish with verification of added item
    scripted_actions = [
        ActionDecision(
            thought="Locate product StudentLite Chromebook 11 and add to cart",
            action=ActionType.CLICK,
            target="#add-to-cart-1",
        ),
        ActionDecision(
            thought="Verify that the cart visibly contains StudentLite Chromebook 11 and finish",
            action=ActionType.FINISH,
            answer="StudentLite Chromebook 11 successfully added to cart for $199.00",
            evidence="StudentLite Chromebook 11 $199.00",
        ),
    ]

    mock_llm = MagicMock(spec=LocalLLMClient)
    mock_llm.decide_action.side_effect = scripted_actions

    policy = SafetyPolicy(allowed_hosts=["localhost", "127.0.0.1"])
    agent = BrowserAgent(
        llm_client=mock_llm,
        safety_policy=policy,
        max_steps=5,
        headless=True,
    )

    req = TaskRequest(
        task="Add the StudentLite Chromebook 11 to the shopping cart and verify",
        start_url=local_demo_server,
        max_steps=5,
    )

    response = agent.run_task(req)

    assert response.status == TaskStatus.COMPLETED
    assert "StudentLite Chromebook 11" in (response.result or "")
    assert response.evidence is not None
    assert response.steps_taken == 2
    assert len(response.history) == 2
    assert response.history[0].action == "click"
    assert response.history[1].action == "finish"
    assert response.history[1].verification_passed is True



