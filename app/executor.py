"""Playwright synchronous action executor with safety enforcement and unambiguous target resolution."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from app.config import settings
from app.logger import app_logger
from app.safety import SafetyPolicy, default_safety_policy
from app.schemas import ActionDecision, ActionResult, ActionType, ScrollDirection, TargetCandidate


class BrowserSession:
    """Manages a single controlled Playwright browser instance."""

    def __init__(self, headless: Optional[bool] = None):
        self.headless = headless if headless is not None else settings.headless
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    def start(self) -> Page:
        """Launch browser and open a single active page."""
        if self._page is not None and not self._page.is_closed():
            return self._page

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        self._context = self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) BrowserPilotVision/1.0",
        )

        self._page = self._context.new_page()
        self._page.set_default_timeout(settings.browser_action_timeout)

        # Handle popups and unexpected tabs safely: automatically close them to enforce single controlled tab
        def on_popup(popup_page: Page):
            if popup_page != self._page:
                try:
                    app_logger.warning(f"Closing unexpected popup tab: {popup_page.url}")
                    popup_page.close()
                except Exception:
                    pass

        self._context.on("page", on_popup)
        return self._page

    @property
    def page(self) -> Page:
        if self._page is None or self._page.is_closed():
            return self.start()
        return self._page

    def stop(self) -> None:
        """Close page, context, and browser cleanly."""
        try:
            if self._page and not self._page.is_closed():
                self._page.close()
        except Exception:
            pass
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    def __enter__(self) -> Page:
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


class ActionExecutor:
    """Executes validated actions through Playwright under strict safety bounds."""

    def __init__(
        self,
        safety_policy: Optional[SafetyPolicy] = None,
        action_timeout: Optional[int] = None,
    ):
        self.safety_policy = safety_policy or default_safety_policy
        self.action_timeout = action_timeout or settings.browser_action_timeout

    def execute(
        self,
        page: Page,
        action: ActionDecision,
        target_map: Optional[Dict[str, TargetCandidate]] = None,
    ) -> ActionResult:
        """Execute a validated ActionDecision on the page and return structured ActionResult."""
        start_time = time.time()
        timestamp = datetime.now(timezone.utc).isoformat()
        url_before = page.url

        result: ActionResult
        try:
            if action.action == ActionType.GOTO:
                result = self._execute_goto(page, action, url_before, timestamp)

            elif action.action == ActionType.CLICK:
                result = self._execute_click(page, action, target_map, url_before, timestamp)

            elif action.action == ActionType.FILL:
                result = self._execute_fill(page, action, target_map, url_before, timestamp)

            elif action.action == ActionType.SCROLL:
                result = self._execute_scroll(page, action, url_before, timestamp)

            elif action.action == ActionType.WAIT:
                result = self._execute_wait(page, action, url_before, timestamp)

            elif action.action == ActionType.FINISH:
                result = ActionResult(
                    action=action,
                    success=True,
                    message=f"Task completed: {action.answer}",
                    url_before=url_before,
                    url_after=page.url,
                    verification_passed=True,
                    verification_evidence=action.evidence,
                    timestamp=timestamp,
                )

            else:
                result = ActionResult(
                    action=action,
                    success=False,
                    message=f"Unsupported action type: {action.action}",
                    error_category="general_error",
                    url_before=url_before,
                    url_after=page.url,
                    timestamp=timestamp,
                )

        except Exception as e:
            app_logger.error(f"Action execution error: {e}")
            result = ActionResult(
                action=action,
                success=False,
                message=f"Execution error: {str(e)}",
                error=str(e),
                error_category="general_error",
                url_before=url_before,
                url_after=page.url,
                timestamp=timestamp,
            )

        result.duration = round(time.time() - start_time, 3)
        return result

    def _execute_goto(
        self, page: Page, action: ActionDecision, url_before: str, timestamp: str
    ) -> ActionResult:
        target_url = (action.url or "").strip()

        # Pre-navigation safety policy check
        is_safe, reason = self.safety_policy.validate_url(target_url)
        if not is_safe:
            return ActionResult(
                action=action,
                success=False,
                message=f"Navigation blocked by safety policy: {reason}",
                error=reason,
                error_category="safety_violation",
                url_before=url_before,
                url_after=url_before,
                timestamp=timestamp,
            )

        page.goto(
            target_url,
            timeout=settings.page_load_timeout,
            wait_until="domcontentloaded",
        )

        # Post-navigation redirect check
        current_url = page.url
        is_dest_safe, redirect_reason = self.safety_policy.validate_url(current_url)
        if not is_dest_safe:
            page.goto("about:blank")
            return ActionResult(
                action=action,
                success=False,
                message=f"Post-redirect destination blocked: {redirect_reason}",
                error=redirect_reason,
                error_category="safety_violation",
                url_before=url_before,
                url_after="about:blank",
                timestamp=timestamp,
            )

        return ActionResult(
            action=action,
            success=True,
            message=f"Navigated successfully to {current_url}",
            url_before=url_before,
            url_after=current_url,
            timestamp=timestamp,
        )

    def _resolve_locator(
        self,
        page: Page,
        target_key: str,
        target_map: Optional[Dict[str, TargetCandidate]],
    ) -> Tuple[Optional[Any], Optional[TargetCandidate], str]:
        """Resolve target to an unambiguous Playwright locator."""
        target_key_clean = target_key.strip()
        matched_candidate: Optional[TargetCandidate] = None

        # 1. Lookup in target map by ID (e.g. "1") or accessible name
        if target_map:
            if target_key_clean in target_map:
                matched_candidate = target_map[target_key_clean]
            elif target_key_clean.lower() in target_map:
                matched_candidate = target_map[target_key_clean.lower()]

        if matched_candidate and matched_candidate.selector:
            try:
                loc = page.locator(matched_candidate.selector).first
                if loc.count() > 0:
                    return loc, matched_candidate, ""
                else:
                    return None, matched_candidate, f"Element '{matched_candidate.name}' (id={matched_candidate.id}) is stale and no longer in the DOM."
            except Exception:
                pass

        # 2. Try role and accessible name matching
        for role in ["button", "link", "textbox", "searchbox", "combobox", "checkbox"]:
            try:
                loc = page.get_by_role(role, name=target_key_clean)
                count = loc.count()
                if count == 1:
                    return loc.first, None, ""
                elif count > 1:
                    return None, None, f"Ambiguous target: multiple elements match role '{role}' and name '{target_key_clean}'."
            except Exception:
                continue

        # 3. Try label and placeholder
        try:
            loc = page.get_by_label(target_key_clean)
            if loc.count() == 1:
                return loc.first, None, ""
            elif loc.count() > 1:
                return None, None, f"Ambiguous target: multiple elements match label '{target_key_clean}'."
        except Exception:
            pass

        try:
            loc = page.get_by_placeholder(target_key_clean)
            if loc.count() == 1:
                return loc.first, None, ""
            elif loc.count() > 1:
                return None, None, f"Ambiguous target: multiple elements match placeholder '{target_key_clean}'."
        except Exception:
            pass

        # 4. Direct CSS/text locator with ambiguity check
        try:
            loc = page.locator(target_key_clean)
            count = loc.count()
            if count == 1:
                return loc.first, None, ""
            elif count > 1:
                return None, None, f"Ambiguous target: selector '{target_key_clean}' matched {count} elements."
        except Exception:
            pass

        return None, None, f"Target '{target_key}' could not be found on the page."

    def _execute_click(
        self,
        page: Page,
        action: ActionDecision,
        target_map: Optional[Dict[str, TargetCandidate]],
        url_before: str,
        timestamp: str,
    ) -> ActionResult:
        target = action.target or ""
        locator, candidate, error_msg = self._resolve_locator(page, target, target_map)

        if not locator:
            category = "missing_target"
            if "ambiguous" in error_msg.lower():
                category = "ambiguous_target"
            elif "stale" in error_msg.lower():
                category = "stale_element"

            return ActionResult(
                action=action,
                success=False,
                message=error_msg,
                error=error_msg,
                error_category=category,
                url_before=url_before,
                url_after=page.url,
                timestamp=timestamp,
            )

        # Safety check: consequential action check
        is_consequential, c_reason = self.safety_policy.check_consequential(action, candidate)
        if is_consequential:
            return ActionResult(
                action=action,
                success=False,
                message=c_reason,
                error=c_reason,
                error_category="safety_violation",
                url_before=url_before,
                url_after=page.url,
                timestamp=timestamp,
            )

        # Check disabled state
        if candidate and candidate.disabled:
            return ActionResult(
                action=action,
                success=False,
                message=f"Cannot click disabled element '{target}'.",
                error="Element is disabled",
                error_category="disabled_element",
                url_before=url_before,
                url_after=page.url,
                timestamp=timestamp,
            )

        try:
            try:
                locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            locator.click(timeout=self.action_timeout)
            page.wait_for_timeout(300)  # Brief settle time
        except Exception as e:
            cat = "timeout" if "timeout" in str(e).lower() else "general_error"
            return ActionResult(
                action=action,
                success=False,
                message=f"Click failed: {str(e)}",
                error=str(e),
                error_category=cat,
                url_before=url_before,
                url_after=page.url,
                timestamp=timestamp,
            )

        # Check for unexpected navigation safety
        dest_safe, d_reason = self.safety_policy.validate_url(page.url)
        if not dest_safe:
            page.goto("about:blank")
            return ActionResult(
                action=action,
                success=False,
                message=f"Click resulted in unsafe navigation: {d_reason}",
                error=d_reason,
                url_before=url_before,
                url_after="about:blank",
                timestamp=timestamp,
            )

        return ActionResult(
            action=action,
            success=True,
            message=f"Clicked target '{target}' successfully.",
            url_before=url_before,
            url_after=page.url,
            timestamp=timestamp,
        )

    def _execute_fill(
        self,
        page: Page,
        action: ActionDecision,
        target_map: Optional[Dict[str, TargetCandidate]],
        url_before: str,
        timestamp: str,
    ) -> ActionResult:
        target = action.target or ""
        value = action.value or ""
        locator, candidate, error_msg = self._resolve_locator(page, target, target_map)

        if not locator:
            category = "missing_target"
            if "ambiguous" in error_msg.lower():
                category = "ambiguous_target"
            elif "stale" in error_msg.lower():
                category = "stale_element"

            return ActionResult(
                action=action,
                success=False,
                message=error_msg,
                error=error_msg,
                error_category=category,
                url_before=url_before,
                url_after=page.url,
                timestamp=timestamp,
            )

        # Safety check: consequential action check
        is_consequential, c_reason = self.safety_policy.check_consequential(action, candidate)
        if is_consequential:
            return ActionResult(
                action=action,
                success=False,
                message=c_reason,
                error=c_reason,
                error_category="safety_violation",
                url_before=url_before,
                url_after=page.url,
                timestamp=timestamp,
            )

        try:
            try:
                locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            locator.fill(value, timeout=self.action_timeout)
        except Exception as e:
            cat = "timeout" if "timeout" in str(e).lower() else "general_error"
            return ActionResult(
                action=action,
                success=False,
                message=f"Fill failed on '{target}': {str(e)}",
                error=str(e),
                error_category=cat,
                url_before=url_before,
                url_after=page.url,
                timestamp=timestamp,
            )

        return ActionResult(
            action=action,
            success=True,
            message=f"Filled '{target}' with input.",
            url_before=url_before,
            url_after=page.url,
            timestamp=timestamp,
        )

    def _execute_scroll(
        self, page: Page, action: ActionDecision, url_before: str, timestamp: str
    ) -> ActionResult:
        direction = action.direction or ScrollDirection.DOWN
        amount = action.amount or 500
        delta_y = amount if direction == ScrollDirection.DOWN else -amount

        try:
            page.mouse.wheel(0, delta_y)
            page.wait_for_timeout(200)
            return ActionResult(
                action=action,
                success=True,
                message=f"Scrolled {direction.value} by {amount}px.",
                url_before=url_before,
                url_after=page.url,
                timestamp=timestamp,
            )
        except Exception as e:
            return ActionResult(
                action=action,
                success=False,
                message=f"Scroll failed: {str(e)}",
                error=str(e),
                url_before=url_before,
                url_after=page.url,
                timestamp=timestamp,
            )

    def _execute_wait(
        self, page: Page, action: ActionDecision, url_before: str, timestamp: str
    ) -> ActionResult:
        seconds = action.seconds or 1.0
        try:
            time.sleep(seconds)
            return ActionResult(
                action=action,
                success=True,
                message=f"Waited for {seconds} seconds.",
                url_before=url_before,
                url_after=page.url,
                timestamp=timestamp,
            )
        except Exception as e:
            return ActionResult(
                action=action,
                success=False,
                message=f"Wait interrupted: {str(e)}",
                error=str(e),
                url_before=url_before,
                url_after=page.url,
                timestamp=timestamp,
            )
