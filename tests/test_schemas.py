"""Tests for action schemas, validation rules, and input limits."""

import pytest
from pydantic import ValidationError
from app.schemas import (
    ActionDecision,
    ActionType,
    ScrollDirection,
    TaskRequest,
    TaskStatus,
)


def test_valid_click_action():
    data = {
        "thought": "Clicking the search submit button",
        "action": "click",
        "target": "search-btn",
    }
    decision = ActionDecision.model_validate(data)
    assert decision.action == ActionType.CLICK
    assert decision.target == "search-btn"
    assert decision.thought == "Clicking the search submit button"


def test_valid_fill_action():
    data = {
        "thought": "Entering search term 'chromebook'",
        "action": "fill",
        "target": "#search-input",
        "value": "chromebook",
    }
    decision = ActionDecision.model_validate(data)
    assert decision.action == ActionType.FILL
    assert decision.target == "#search-input"
    assert decision.value == "chromebook"


def test_valid_goto_action():
    data = {
        "thought": "Navigating to home page",
        "action": "goto",
        "url": "http://127.0.0.1:5000/",
    }
    decision = ActionDecision.model_validate(data)
    assert decision.action == ActionType.GOTO
    assert decision.url == "http://127.0.0.1:5000/"


def test_valid_scroll_and_wait_actions():
    data_scroll = {
        "thought": "Scrolling down to view more laptops",
        "action": "scroll",
        "direction": "down",
        "amount": 600,
    }
    dec_scroll = ActionDecision.model_validate(data_scroll)
    assert dec_scroll.action == ActionType.SCROLL
    assert dec_scroll.direction == ScrollDirection.DOWN
    assert dec_scroll.amount == 600

    data_wait = {
        "thought": "Waiting for results to render",
        "action": "wait",
        "seconds": 2.5,
    }
    dec_wait = ActionDecision.model_validate(data_wait)
    assert dec_wait.action == ActionType.WAIT
    assert dec_wait.seconds == 2.5


def test_valid_finish_action():
    data = {
        "thought": "Found the cheapest laptop",
        "action": "finish",
        "answer": "The cheapest laptop is StudentLite Chromebook 11 for $199.00",
        "evidence": "$199.00 StudentLite Chromebook 11",
    }
    decision = ActionDecision.model_validate(data)
    assert decision.action == ActionType.FINISH
    assert "StudentLite" in decision.answer
    assert decision.evidence is not None


def test_invalid_action_name():
    data = {
        "thought": "Attempting arbitrary action",
        "action": "execute_shell",
        "target": "dir",
    }
    with pytest.raises(ValidationError):
        ActionDecision.model_validate(data)


def test_missing_required_target_for_click():
    data = {
        "thought": "Clicking without target",
        "action": "click",
        "target": "",
    }
    with pytest.raises(ValidationError) as exc:
        ActionDecision.model_validate(data)
    assert "requires a non-empty 'target'" in str(exc.value)


def test_missing_required_value_for_fill():
    data = {
        "thought": "Filling without value",
        "action": "fill",
        "target": "search-box",
    }
    with pytest.raises(ValidationError) as exc:
        ActionDecision.model_validate(data)
    assert "requires a non-empty 'value'" in str(exc.value)


def test_forbidden_extra_fields():
    data = {
        "thought": "Trying to inject unauthorized field",
        "action": "wait",
        "seconds": 1.0,
        "arbitrary_payload": "rm -rf /",
    }
    with pytest.raises(ValidationError):
        ActionDecision.model_validate(data)


def test_disallowed_code_injection_in_text():
    dangerous_inputs = [
        "javascript:alert(1)",
        "<script>window.location='evil.com'</script>",
        "eval('hack()')",
        "__import__('os').system('dir')",
        "powershell -enc aW52b2tl",
    ]
    for payload in dangerous_inputs:
        data = {
            "thought": payload,
            "action": "wait",
            "seconds": 1.0,
        }
        with pytest.raises(ValidationError) as exc:
            ActionDecision.model_validate(data)
        assert "Dangerous or executable code detected" in str(exc.value)


def test_value_length_bounds():
    oversized_value = "A" * 600
    data = {
        "thought": "Testing max length",
        "action": "fill",
        "target": "input",
        "value": oversized_value,
    }
    with pytest.raises(ValidationError):
        ActionDecision.model_validate(data)


def test_task_request_validation():
    # Valid
    req = TaskRequest(
        task="Find laptops under $500",
        start_url="http://127.0.0.1:5000",
    )
    assert req.task == "Find laptops under $500"
    assert req.max_steps is None

    # Invalid - too short task
    with pytest.raises(ValidationError):
        TaskRequest(task="ab", start_url="http://127.0.0.1:5000")
