"""Page observer for extracting compact semantic browser state and interactive targets."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from playwright.sync_api import Page

from app.config import settings
from app.logger import app_logger
from app.safety import default_safety_policy
from app.schemas import PageObservation, TargetCandidate


class PageObserver:
    """Builds compact, token-efficient representations of live browser pages."""

    def __init__(self, max_chars: Optional[int] = None):
        self.max_chars = max_chars or settings.max_observation_chars

    def observe(self, page: Page, capture_screenshot: bool = False) -> Tuple[PageObservation, Dict[str, TargetCandidate]]:
        """Observe current page state, returning structured PageObservation and target lookup table."""
        url = page.url
        title = page.title()

        # Extract visible, sanitized body text
        raw_text = self._extract_visible_text(page)
        truncated = len(raw_text) > self.max_chars
        bounded_text = raw_text[: self.max_chars]
        wrapped_text = default_safety_policy.wrap_untrusted_page_text(bounded_text)

        # Extract interactive candidate elements
        candidates, target_map = self._extract_interactive_elements(page)

        # Capture screenshot if requested
        screenshot_path = None
        if capture_screenshot:
            screenshot_path = self.take_screenshot(page)

        obs = PageObservation(
            url=url,
            title=title,
            visible_text=wrapped_text,
            interactive_elements=candidates,
            char_count=len(bounded_text),
            truncated=truncated,
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )

        return obs, target_map

    def _extract_visible_text(self, page: Page) -> str:
        """Extract clean, visible body text excluding scripts, styles, and hidden elements."""
        try:
            # JavaScript extraction script for visible text content
            text_extract_js = """() => {
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_TEXT,
                    {
                        acceptNode: function(node) {
                            if (!node.parentElement) return NodeFilter.FILTER_REJECT;
                            const tag = node.parentElement.tagName.toLowerCase();
                            if (tag === 'script' || tag === 'style' || tag === 'noscript') {
                                return NodeFilter.FILTER_REJECT;
                            }
                            const style = window.getComputedStyle(node.parentElement);
                            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                                return NodeFilter.FILTER_REJECT;
                            }
                            return NodeFilter.FILTER_ACCEPT;
                        }
                    }
                );
                const texts = [];
                let node;
                while (node = walker.nextNode()) {
                    const txt = node.textContent.trim();
                    if (txt) texts.push(txt);
                }
                return texts.join(' ');
            }"""
            extracted = page.evaluate(text_extract_js)
            if not extracted:
                # Fallback to locator
                extracted = page.locator("body").inner_text(timeout=2000) or ""
            # Clean excessive whitespaces
            clean = re.sub(r"\s+", " ", extracted).strip()
            return clean
        except Exception as e:
            app_logger.warning(f"Error extracting visible text: {e}")
            return "(Unable to read page text)"

    def _extract_interactive_elements(
        self, page: Page
    ) -> Tuple[List[TargetCandidate], Dict[str, TargetCandidate]]:
        """Extract visible, actionable interactive elements (buttons, inputs, links)."""
        candidates: List[TargetCandidate] = []
        target_map: Dict[str, TargetCandidate] = {}

        # JavaScript element scanner that returns accessible semantic descriptors
        scanner_js = """() => {
            const results = [];
            const interactiveSelector = 'button, a[href], input:not([type="hidden"]), select, textarea, [role="button"], [role="link"], [role="checkbox"], [role="radio"]';
            const elements = Array.from(document.querySelectorAll(interactiveSelector));

            let currentId = 1;
            for (const el of elements) {
                // Check visibility
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                if (
                    rect.width <= 0 ||
                    rect.height <= 0 ||
                    style.display === 'none' ||
                    style.visibility === 'hidden' ||
                    style.opacity === '0'
                ) {
                    continue;
                }

                const tag = el.tagName.toLowerCase();
                let role = el.getAttribute('role') || '';
                if (!role) {
                    if (tag === 'button') role = 'button';
                    else if (tag === 'a') role = 'link';
                    else if (tag === 'input') role = el.type || 'input';
                    else if (tag === 'select') role = 'combobox';
                    else if (tag === 'textarea') role = 'textbox';
                    else role = tag;
                }

                // Compute accessible name / label
                let name = el.getAttribute('aria-label') || '';
                if (!name && el.labels && el.labels.length > 0) {
                    name = el.labels[0].innerText || '';
                }
                if (!name && el.innerText) {
                    name = el.innerText.trim();
                }
                if (!name && el.value && (tag === 'input' || tag === 'button')) {
                    name = el.value.trim();
                }
                if (!name && el.placeholder) {
                    name = el.placeholder.trim();
                }

                // Contextual enrichment for generic button/link texts
                const genericWords = /^(add to cart|view details|buy now|buy|details|select|more|view|order|shop now)$/i;
                if (name && genericWords.test(name)) {
                    const card = el.closest('article, .product-card, .card, [data-id], li, tr');
                    if (card) {
                        const heading = card.querySelector('h1, h2, h3, h4, .product-title, .title, strong');
                        if (heading && heading.innerText) {
                            name = name + ' - ' + heading.innerText.trim();
                        }
                    }
                }

                // Shorten name if too long
                name = name.replace(/\\s+/g, ' ').slice(0, 100).trim();

                // Build a reliable selector
                let selector = '';
                if (el.id) {
                    selector = '#' + CSS.escape(el.id);
                } else if (name && (role === 'button' || role === 'link')) {
                    selector = `${tag}:has-text("${name.replace(/"/g, '\\\\"')}")`;
                } else if (el.name) {
                    selector = `${tag}[name="${CSS.escape(el.name)}"]`;
                } else {
                    selector = `${tag}:nth-of-type(${currentId})`;
                }

                results.push({
                    id: currentId,
                    role: role,
                    name: name || `[Unnamed ${role}]`,
                    tag: tag,
                    selector: selector,
                    disabled: !!el.disabled,
                    input_type: el.type || null,
                    placeholder: el.placeholder || null,
                    href: el.getAttribute('href') || null
                });

                currentId++;
                if (currentId > 60) break; // Keep candidate list bounded
            }
            return results;
        }"""

        try:
            raw_elements = page.evaluate(scanner_js)
            for item in raw_elements:
                candidate = TargetCandidate(
                    id=item["id"],
                    role=item["role"],
                    name=item["name"],
                    selector=item["selector"],
                    tag=item["tag"],
                    disabled=item["disabled"],
                    input_type=item["input_type"],
                    placeholder=item["placeholder"],
                    href=item["href"],
                )
                candidates.append(candidate)
                # Map by numeric string id ("1") and by name
                target_map[str(candidate.id)] = candidate
                if candidate.name and candidate.name not in target_map:
                    target_map[candidate.name.lower()] = candidate
        except Exception as e:
            app_logger.warning(f"Error scanning interactive elements: {e}")

        return candidates, target_map

    def revalidate_element(self, page: Page, candidate: TargetCandidate) -> Tuple[bool, str]:
        """Revalidate that candidate element is still present in DOM, visible, and valid before acting."""
        if not candidate.selector:
            return False, "Target candidate has no valid selector."
        try:
            loc = page.locator(candidate.selector).first
            if loc.count() == 0:
                return False, f"Target '{candidate.name}' (id={candidate.id}) is no longer present in DOM (stale element)."
            if not loc.is_visible():
                return False, f"Target '{candidate.name}' (id={candidate.id}) is no longer visible."
            return True, ""
        except Exception as e:
            return False, f"Error revalidating target '{candidate.name}': {str(e)}"

    def take_screenshot(self, page: Page, filename: Optional[str] = None) -> Path:
        """Capture screenshot and store it in screenshots directory."""
        settings.screenshots_dir.mkdir(parents=True, exist_ok=True)
        if not filename:
            import uuid
            filename = f"screen_{uuid.uuid4().hex[:8]}.png"
        path = settings.screenshots_dir / filename
        page.screenshot(path=str(path), full_page=False)
        return path
