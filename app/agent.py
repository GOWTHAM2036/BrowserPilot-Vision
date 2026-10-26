"""Autonomous Observe-Plan-Execute-Verify browser agent loop."""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.config import settings
from app.executor import ActionExecutor, BrowserSession
from app.llm import LocalLLMClient
from app.logger import TaskLogger, app_logger
from app.observer import PageObserver
from app.safety import SafetyPolicy, default_safety_policy
from app.schemas import (
    ActionDecision,
    ActionResult,
    ActionType,
    PageObservation,
    TaskRequest,
    TaskResponse,
    TaskStatus,
    TaskStepRecord,
)


class BrowserAgent:
    """Manages the full lifecycle of a single browser automation task."""

    def __init__(
        self,
        llm_client: Optional[LocalLLMClient] = None,
        safety_policy: Optional[SafetyPolicy] = None,
        max_steps: Optional[int] = None,
        headless: Optional[bool] = None,
        step_callback: Optional[Callable[[TaskStepRecord], None]] = None,
    ):
        self.llm_client = llm_client or LocalLLMClient()
        self.safety_policy = safety_policy or default_safety_policy
        self.max_steps = max_steps or settings.max_agent_steps
        self.headless = headless if headless is not None else settings.headless
        self.step_callback = step_callback
        self.observer = PageObserver()
        self.executor = ActionExecutor(safety_policy=self.safety_policy)
        self._cancelled = False

    def _safe_log_event(self, logger: TaskLogger, event_type: str, data: Dict[str, Any], step: Optional[int] = None) -> None:
        try:
            logger.log_event(event_type, data, step=step)
        except Exception as e:
            app_logger.warning(f"Logger event failed: {e}")

    def _safe_log_action(self, logger: TaskLogger, **kwargs: Any) -> None:
        try:
            logger.log_action(**kwargs)
        except Exception as e:
            app_logger.warning(f"Logger action failed: {e}")

    def _safe_log_error(self, logger: TaskLogger, **kwargs: Any) -> None:
        try:
            logger.log_error(**kwargs)
        except Exception as e:
            app_logger.warning(f"Logger error failed: {e}")

    def cancel(self) -> None:
        """Signal the agent loop to cancel at the next checkpoint."""
        self._cancelled = True

    def run_task(self, request: TaskRequest) -> TaskResponse:
        """Execute the observe-plan-execute-verify loop for the given task request."""
        task_id = f"task_{uuid.uuid4().hex[:10]}"
        task_logger = TaskLogger(task_id=task_id)
        max_steps = request.max_steps or self.max_steps
        selected_model = request.model or settings.default_model

        created_at = datetime.now(timezone.utc).isoformat()
        history: List[TaskStepRecord] = []
        recent_llm_history: List[Dict[str, Any]] = []

        response = TaskResponse(
            task_id=task_id,
            status=TaskStatus.RUNNING,
            task=request.task,
            start_url=request.start_url,
            model=selected_model,
            max_steps=max_steps,
            created_at=created_at,
            updated_at=created_at,
            history=history,
        )

        self._safe_log_event(task_logger, "task_start", {"request": request.model_dump()})

        # 1. Validate starting URL
        is_safe, reason = self.safety_policy.validate_url(request.start_url)
        if not is_safe:
            msg = f"Task aborted: Starting URL is blocked by safety policy ({reason})"
            app_logger.warning(msg)
            self._safe_log_error(task_logger, step=None, error_message=msg)
            response.status = TaskStatus.BLOCKED
            response.error = msg
            response.updated_at = datetime.now(timezone.utc).isoformat()
            return response

        # 2. Launch browser session
        browser_session = BrowserSession(headless=self.headless)
        try:
            page = browser_session.start()

            # Navigate to initial page
            try:
                page.goto(request.start_url, timeout=settings.page_load_timeout, wait_until="domcontentloaded")
            except Exception as e:
                err_msg = f"Failed to load start URL {request.start_url}: {e}"
                self._safe_log_error(task_logger, step=0, error_message=err_msg)
                response.status = TaskStatus.FAILED
                response.error = err_msg
                response.updated_at = datetime.now(timezone.utc).isoformat()
                return response

            current_step = 1
            consecutive_failures = 0
            last_failed_error: Optional[str] = None

            while current_step <= max_steps:
                if self._cancelled:
                    app_logger.info(f"Task {task_id} was cancelled by user.")
                    self._safe_log_event(task_logger, "task_cancelled", {"step": current_step})
                    response.status = TaskStatus.CANCELLED
                    response.updated_at = datetime.now(timezone.utc).isoformat()
                    return response

                # 3. Observe current page state
                capture_screen = request.use_vision and current_step > 1
                obs, target_map = self.observer.observe(page, capture_screenshot=capture_screen)

                # 4. Ask local LLM for structured action
                try:
                    action_decision = self.llm_client.decide_action(
                        task=request.task,
                        observation=obs,
                        step=current_step,
                        max_steps=max_steps,
                        recent_history=recent_llm_history,
                        model=selected_model,
                        screenshot_path=obs.screenshot_path if capture_screen else None,
                    )
                except Exception as e:
                    app_logger.error(f"Step {current_step}: LLM decision failed: {e}")
                    self._safe_log_error(task_logger, step=current_step, error_message=str(e))
                    consecutive_failures += 1
                    if consecutive_failures > settings.max_recovery_attempts:
                        response.status = TaskStatus.FAILED
                        response.error = f"LLM failed after {consecutive_failures} recovery attempts: {e}"
                        response.updated_at = datetime.now(timezone.utc).isoformat()
                        return response
                    current_step += 1
                    continue

                # 5. Check if action is finish
                if action_decision.action == ActionType.FINISH:
                    # 8. Verify whether the expected outcome occurred using observable browser state
                    verif_passed, verif_evidence = self._verify_finish(action_decision, obs)
                    if verif_passed:
                        self._safe_log_action(
                            task_logger,
                            step=current_step,
                            action=action_decision.model_dump(),
                            outcome={"success": True, "message": "Finish verified"},
                            verification_passed=True,
                            verification_evidence=verif_evidence,
                            observation_summary=obs.visible_text[:200],
                            duration=0.0,
                        )
                        record = TaskStepRecord(
                            step=current_step,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            thought=action_decision.thought,
                            action=action_decision.action.value,
                            target=action_decision.target,
                            value=action_decision.value,
                            url=action_decision.url,
                            success=True,
                            verification_passed=True,
                            message=f"Task complete: {action_decision.answer}",
                            evidence=verif_evidence,
                        )
                        history.append(record)
                        response.history = list(history)
                        if self.step_callback:
                            self.step_callback(record)

                        response.status = TaskStatus.COMPLETED
                        response.result = action_decision.answer
                        response.evidence = verif_evidence
                        response.steps_taken = current_step
                        response.updated_at = datetime.now(timezone.utc).isoformat()
                        return response
                    else:
                        # Verification failed: Finish cannot be accepted without proof
                        fail_msg = f"Finish rejected: Claimed evidence not found in observable browser state."
                        app_logger.warning(f"Step {current_step}: {fail_msg}")
                        consecutive_failures += 1
                        last_failed_error = fail_msg
                        recent_llm_history.append({
                            "step": current_step,
                            "action": "finish",
                            "target": None,
                            "success": False,
                            "message": fail_msg,
                        })
                        if consecutive_failures > settings.max_recovery_attempts:
                            response.status = TaskStatus.UNVERIFIED
                            response.error = fail_msg
                            response.updated_at = datetime.now(timezone.utc).isoformat()
                            return response
                        current_step += 1
                        continue

                # 6. Execute action through Playwright
                exec_result = self.executor.execute(page, action_decision, target_map)

                # 7. Observe resulting page state
                obs_after, _ = self.observer.observe(page, capture_screenshot=False)

                # 8. Verify action outcome
                verif_passed, verif_note = self._verify_action_outcome(
                    action_decision, exec_result, obs, obs_after
                )
                exec_result.verification_passed = verif_passed
                exec_result.verification_evidence = verif_note

                # 9. Record evidence in execution log
                self._safe_log_action(
                    task_logger,
                    step=current_step,
                    action=action_decision.model_dump(),
                    outcome={
                        "success": exec_result.success,
                        "message": exec_result.message,
                        "error": exec_result.error,
                        "error_category": exec_result.error_category,
                        "url_before": exec_result.url_before,
                        "url_after": exec_result.url_after,
                    },
                    verification_passed=verif_passed,
                    verification_evidence=verif_note,
                    recovery_attempt=consecutive_failures if not exec_result.success else 0,
                    observation_summary=obs_after.visible_text[:200],
                    error_category=exec_result.error_category,
                    duration=exec_result.duration,
                )

                step_record = TaskStepRecord(
                    step=current_step,
                    timestamp=exec_result.timestamp,
                    thought=action_decision.thought,
                    action=action_decision.action.value,
                    target=action_decision.target,
                    value=action_decision.value,
                    url=action_decision.url,
                    success=exec_result.success,
                    verification_passed=verif_passed,
                    message=exec_result.message,
                    evidence=verif_note,
                    duration=exec_result.duration,
                    error_category=exec_result.error_category,
                )
                history.append(step_record)
                response.history = list(history)
                if self.step_callback:
                    self.step_callback(step_record)

                recent_llm_history.append({
                    "step": current_step,
                    "action": action_decision.action.value,
                    "target": action_decision.target,
                    "success": exec_result.success,
                    "message": exec_result.message,
                })

                # Anti-thrashing: detect consecutive identical actions with no page change
                if len(history) >= 2:
                    prev = history[-2]
                    if (
                        step_record.action == prev.action
                        and step_record.target == prev.target
                        and obs_after.url == obs.url
                        and obs_after.visible_text == obs.visible_text
                    ):
                        loop_warning = (
                            f"Action '{step_record.action}' on '{step_record.target}' produced no visible page change. "
                            "Avoid repeating this action; choose an alternative target or element."
                        )
                        recent_llm_history[-1]["message"] += f" [{loop_warning}]"

                if not exec_result.success:
                    consecutive_failures += 1
                    last_failed_error = exec_result.message

                    # Vision fallback: capture screenshot and visually analyze if enabled
                    if request.use_vision:
                        try:
                            screen_file = self.observer.take_screenshot(page)
                            vision_insight = self.llm_client.analyze_vision(
                                screenshot_path=screen_file,
                                prompt=f"Task: '{request.task}'. Action failed: '{exec_result.message}'. What interactive elements or buttons are visible on screen?",
                                model=selected_model,
                            )
                            if vision_insight:
                                recent_llm_history[-1]["message"] += f" [Vision Fallback: {vision_insight[:180]}]"
                        except Exception as ve:
                            app_logger.warning(f"Vision fallback check failed: {ve}")

                    if "blocked by safety policy" in exec_result.message.lower():
                        response.status = TaskStatus.BLOCKED
                        response.error = exec_result.message
                        response.steps_taken = current_step
                        response.updated_at = datetime.now(timezone.utc).isoformat()
                        return response

                    if consecutive_failures > settings.max_recovery_attempts:
                        response.status = TaskStatus.FAILED
                        response.error = (
                            f"Action failed after {consecutive_failures} recovery attempts: {last_failed_error}"
                        )
                        response.steps_taken = current_step
                        response.updated_at = datetime.now(timezone.utc).isoformat()
                        return response
                else:
                    consecutive_failures = 0

                current_step += 1

            # Reached step limit
            response.history = list(history)
            response.status = TaskStatus.STEP_LIMIT_REACHED
            response.error = f"Agent reached the maximum step limit of {max_steps} actions."
            response.steps_taken = max_steps
            response.updated_at = datetime.now(timezone.utc).isoformat()
            return response

        finally:
            # Ensure browser closes when task ends or fails
            browser_session.stop()

    def _verify_finish(
        self, action: ActionDecision, obs: PageObservation
    ) -> tuple[bool, Optional[str]]:
        """Verify that the claimed finish result and evidence are observable on the page."""
        stopwords = {
            "this", "that", "with", "from", "have", "more", "stock", "page",
            "store", "product", "demo", "view", "details", "cheapest", "laptop",
            "priced", "price", "only", "also", "best", "true", "null", "item",
            "order", "about", "there", "their", "which",
        }

        page_text_lower = obs.visible_text.lower()
        title_lower = obs.title.lower()
        elements_text = " ".join(el.name.lower() for el in obs.interactive_elements)
        combined_observable = f"{page_text_lower} {title_lower} {elements_text}"

        evidence = (action.evidence or "").strip()
        answer = (action.answer or "").strip()

        # If model provided explicit evidence, verify specific content words are present on page
        if evidence:
            words = [
                re.sub(r"[^\w\.]", "", w).strip().lower()
                for w in evidence.split()
                if len(w.strip()) > 2 and w.strip().lower() not in stopwords
            ]
            words = [w for w in words if w]
            if words:
                matched = sum(1 for w in words if w in combined_observable)
                if matched >= max(1, int(len(words) * 0.6)):
                    return True, evidence

        # Also check if answer contains specific verifiable content words present on page
        if answer:
            words = [
                re.sub(r"[^\w\.]", "", w).strip().lower()
                for w in answer.split()
                if len(w.strip()) > 2 and w.strip().lower() not in stopwords
            ]
            words = [w for w in words if w]
            if words:
                matched = sum(1 for w in words if w in combined_observable)
                if matched >= max(1, int(len(words) * 0.6)):
                    return True, f"Verified against observable page state: {answer[:120]}"

        return False, None

    def _verify_action_outcome(
        self,
        action: ActionDecision,
        result: ActionResult,
        obs_before: PageObservation,
        obs_after: PageObservation,
    ) -> tuple[bool, Optional[str]]:
        """Verify whether an action altered the browser state as expected."""
        if not result.success:
            return False, result.error

        act = action.action
        if act == ActionType.GOTO:
            if obs_after.url != obs_before.url or obs_after.title:
                return True, f"URL updated to: {obs_after.url}"
            return False, "URL did not change after navigation"

        elif act == ActionType.CLICK:
            # Did URL change or did content change?
            if obs_after.url != obs_before.url:
                return True, f"Navigation to {obs_after.url} occurred."
            if obs_after.visible_text != obs_before.visible_text:
                return True, "Page content updated after click."
            return True, "Click executed on element."

        elif act == ActionType.FILL:
            return True, f"Input filled with '{action.value}'"

        elif act in (ActionType.SCROLL, ActionType.WAIT):
            return True, result.message

        return True, None
