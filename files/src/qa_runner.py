"""qa_runner.py - Browser-driven reusable website QA automation.

The QA runner crawls a bounded set of internal pages, interacts with common UI
controls, records pass/fail test cases, and captures screenshots for failures.
It is intentionally conservative around destructive actions so the tool can be
used against arbitrary public websites without logging out, purchasing, deleting,
or uploading user data.

Login handling:
  If the start URL is a login page (password field detected), the runner will
  prompt the operator for credentials via the terminal, fill them in, and
  continue testing on the authenticated session.
"""

from dataclasses import dataclass, field
from datetime import datetime
import getpass
import os
import re
from urllib.parse import urldefrag, urljoin, urlparse

from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from src.qa_logger import StepLogger


TEXT_INPUT_TYPES = {
    "",
    "text",
    "email",
    "search",
    "tel",
    "url",
    "number",
    "password",
}

SKIP_ACTION_RE = re.compile(
    r"\b(delete|remove|logout|log out|sign out|pay|checkout|purchase|buy|order|"
    r"subscribe|unsubscribe|cancel|confirm|book|reserve|upload|download)\b",
    re.I,
)


@dataclass
class QATestCase:
    test_case_id: str
    test_scenario: str
    steps_to_execute: str
    expected_result: str
    actual_result: str
    status: str
    screenshot_reference: str = ""


@dataclass
class QARunReport:
    url: str
    final_url: str
    started_at: str
    finished_at: str
    pages_tested: int = 0
    selector_file_path: str = ""
    test_cases: list[QATestCase] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for tc in self.test_cases if tc.status == "Pass")

    @property
    def failed(self) -> int:
        return sum(1 for tc in self.test_cases if tc.status == "Fail")

    @property
    def total(self) -> int:
        return len(self.test_cases)


class QARunner:
    def __init__(
        self,
        headless: bool = True,
        timeout: int = 20000,
        max_pages: int = 5,
        max_links_per_page: int = 100,
        max_controls_per_type: int = 8,
    ):
        self.headless = headless
        self.timeout = timeout
        self.max_pages = max_pages
        self.max_links_per_page = max_links_per_page
        self.max_controls_per_type = max_controls_per_type
        self._counter = 1
        self._logger = StepLogger()
        self._tested_elements: set[str] = set()

    def _next_id(self) -> str:
        test_id = f"TC_{self._counter:03d}"
        self._counter += 1
        return test_id

    # ── Deduplication helpers ───────────────────────────────────────────────

    def _elem_key(self, item: dict) -> str:
        return (
            item.get("xpath")
            or item.get("css")
            or f"{item.get('tag')}::{item.get('text', '')[:60]}"
        )

    def _is_tested(self, item: dict) -> bool:
        return self._elem_key(item) in self._tested_elements

    def _mark_tested(self, item: dict) -> None:
        key = self._elem_key(item)
        if key:
            self._tested_elements.add(key)

    def _btn_key(self, page_url: str, label: str) -> str:
        return f"btn::{page_url}::{label}"

    # ── Clickability validation ─────────────────────────────────────────────

    def _is_truly_clickable(self, page: Page, item: dict) -> bool:
        """Return True when the element has clear clickable intent by design."""
        tag  = (item.get("tag")  or "").lower()
        role = (item.get("role") or "").lower()
        href = (item.get("href") or "").strip()
        if tag in ("button", "a", "summary") or role in ("button", "link", "tab", "menuitem"):
            return True
        if href and not href.startswith(("javascript:void", "javascript:;")):
            return True
        xpath = item.get("xpath") or ""
        if xpath:
            try:
                has_event = page.evaluate(
                    """(xpath) => {
                        const el = document.evaluate(xpath, document, null,
                            XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                        if (!el) return false;
                        return !!(el.onclick || el.getAttribute('onclick') ||
                                  el.getAttribute('data-action') ||
                                  el.getAttribute('ng-click'));
                    }""",
                    xpath,
                )
                if has_event:
                    return True
            except Exception:
                pass
        return False

    # ── Skip log shortcut ───────────────────────────────────────────────────

    def _log_skip(self, action: str, element: str, reason: str = "already tested") -> None:
        self._logger.skip(action, element, reason)

    def _snapshot(self, page: Page, scenario: str, screenshots_dir: str) -> str:
        """Save a PNG named after the failing scenario and timestamp.

        Returns the absolute path so it is actionable from the Excel report.
        """
        os.makedirs(screenshots_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r"[^\w]", "_", scenario)[:40].strip("_")
        filename = f"{safe}_{ts}.png"
        path = os.path.abspath(os.path.join(screenshots_dir, filename))
        page.screenshot(path=path, full_page=True)
        return path

    def _add_case(
        self,
        report: QARunReport,
        page: Page,
        screenshots_dir: str,
        scenario: str,
        steps: str,
        expected: str,
        actual: str,
        passed: bool,
    ) -> None:
        tc_id = self._next_id()
        # Screenshots are captured ONLY for failed test cases
        screenshot = ""
        if not passed:
            try:
                screenshot = self._snapshot(page, scenario, screenshots_dir)
            except Exception:
                screenshot = ""

        report.test_cases.append(
            QATestCase(
                test_case_id=tc_id,
                test_scenario=scenario,
                steps_to_execute=steps,
                expected_result=expected,
                actual_result=actual,
                status="Pass" if passed else "Fail",
                screenshot_reference=screenshot,
            )
        )

        # ── Real-time console step log ──────────────────────────────────────
        self._logger.log(scenario, steps, actual, passed)
        if screenshot:
            self._logger.screenshot_saved(screenshot)

    def _normalize_url(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            return "https://" + url
        return url

    def _same_host(self, target_url: str, base_host: str) -> bool:
        return urlparse(target_url).netloc == base_host

    def _clean_url(self, current_url: str, href: str) -> str:
        joined = urljoin(current_url, href)
        return urldefrag(joined)[0]

    def _safe_label(self, locator) -> str:
        try:
            text = (locator.inner_text(timeout=1000) or "").strip()
        except Exception:
            text = ""
        try:
            label = locator.get_attribute("aria-label", timeout=1000) or ""
        except Exception:
            label = ""
        try:
            value = locator.get_attribute("value", timeout=1000) or ""
        except Exception:
            value = ""
        return (text or label or value or "(no label)").replace("\n", " ")[:80]

    def _is_safe_action(self, text: str) -> bool:
        return SKIP_ACTION_RE.search(text or "") is None

    def _selector_report_path(self, url: str, out_dir: str = "reports") -> str:
        os.makedirs(out_dir, exist_ok=True)
        host = urlparse(url).netloc.replace(".", "_").replace(":", "_")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(out_dir, f"selectors_{host}_{ts}.txt")

    def _goto(self, page: Page, url: str):
        response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PlaywrightTimeoutError:
            pass
        return response

    def _discover_pages(self, page: Page, start_url: str) -> list[str]:
        base_host = urlparse(start_url).netloc
        discovered = [start_url]
        seen = {start_url}

        try:
            anchors = page.locator("a[href]").evaluate_all(
                """els => els.map(a => ({
                    href: a.getAttribute('href') || '',
                    text: (a.innerText || a.getAttribute('aria-label') || '').trim()
                }))"""
            )
        except Exception:
            anchors = []

        for anchor in anchors:
            href = (anchor.get("href") or "").strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            full_url = self._clean_url(start_url, href)
            parsed = urlparse(full_url)
            if parsed.scheme not in ("http", "https"):
                continue
            if not self._same_host(full_url, base_host):
                continue
            if full_url not in seen:
                seen.add(full_url)
                discovered.append(full_url)
            if len(discovered) >= self.max_pages:
                break

        return discovered

    def _extract_selectors(self, page: Page, page_url: str) -> list[dict]:
        try:
            return page.evaluate(
                """(pageUrl) => {
                    const cssEscape = window.CSS && CSS.escape ? CSS.escape : (v) => String(v).replace(/["\\\\#.:,[\\]>+~*'=\\s]/g, '\\\\$&');
                    const xPathFor = (el) => {
                        if (el.id) return `//*[@id="${el.id.replace(/"/g, '\\"')}"]`;
                        const parts = [];
                        while (el && el.nodeType === Node.ELEMENT_NODE) {
                            let index = 1;
                            let sibling = el.previousElementSibling;
                            while (sibling) {
                                if (sibling.nodeName === el.nodeName) index++;
                                sibling = sibling.previousElementSibling;
                            }
                            parts.unshift(`${el.nodeName.toLowerCase()}[${index}]`);
                            el = el.parentElement;
                        }
                        return '/' + parts.join('/');
                    };
                    const cssFor = (el) => {
                        if (el.id) return `#${cssEscape(el.id)}`;
                        const testId = el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-cy');
                        if (testId) return `${el.tagName.toLowerCase()}[data-testid="${testId.replace(/"/g, '\\"')}"]`;
                        const name = el.getAttribute('name');
                        if (name) return `${el.tagName.toLowerCase()}[name="${name.replace(/"/g, '\\"')}"]`;
                        const aria = el.getAttribute('aria-label');
                        if (aria) return `${el.tagName.toLowerCase()}[aria-label="${aria.replace(/"/g, '\\"')}"]`;
                        const type = el.getAttribute('type');
                        if (type) return `${el.tagName.toLowerCase()}[type="${type.replace(/"/g, '\\"')}"]`;
                        return el.tagName.toLowerCase();
                    };
                    const visible = (el) => {
                        const style = getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                    };
                    const kindFor = (el) => {
                        const tag = el.tagName.toLowerCase();
                        if (/^h[1-6]$/.test(tag)) return 'heading';
                        if (tag === 'a') return 'link';
                        if (tag === 'button' || el.getAttribute('role') === 'button') return 'button';
                        if (tag === 'input' || tag === 'textarea') return 'input';
                        if (tag === 'select') return 'dropdown';
                        if (tag === 'form') return 'form';
                        if (tag === 'svg' || tag === 'img' || tag === 'i') return 'icon';
                        return 'clickable';
                    };
                    const selector = [
                        'a[href]', 'button', '[role="button"]', '[onclick]',
                        'input', 'textarea', 'select', 'form',
                        'summary', 'label', '[tabindex]:not([tabindex="-1"])',
                        'h1,h2,h3,h4,h5,h6', 'svg', 'img[role="button"]',
                        '[aria-label]', '[data-testid]', '[data-test]', '[data-cy]'
                    ].join(',');
                    const seen = new Set();
                    return Array.from(document.querySelectorAll(selector))
                        .filter(el => visible(el) || el.tagName.toLowerCase() === 'form')
                        .map((el, index) => {
                            const xpath = xPathFor(el);
                            const key = `${el.tagName}-${xpath}-${index}`;
                            if (seen.has(key)) return null;
                            seen.add(key);
                            return {
                                page_url: pageUrl,
                                index: index + 1,
                                tag: el.tagName.toLowerCase(),
                                kind: kindFor(el),
                                text: (el.innerText || el.value || el.alt || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ').slice(0, 160),
                                id: el.id || '',
                                name: el.getAttribute('name') || '',
                                type: el.getAttribute('type') || '',
                                role: el.getAttribute('role') || '',
                                href: el.href || el.getAttribute('href') || '',
                                action: el.getAttribute('action') || '',
                                css: cssFor(el),
                                xpath,
                            };
                        })
                        .filter(Boolean);
                }""",
                page_url,
            )
        except Exception:
            return []

    def _write_selector_file(self, path: str, selectors_by_page: dict[str, list[dict]]) -> None:
        lines = [
            "WebScanner Selector Inventory",
            f"Generated: {datetime.now().isoformat()}",
            "",
        ]
        total = 0
        for page_url, selectors in selectors_by_page.items():
            lines.append("=" * 100)
            lines.append(f"PAGE: {page_url}")
            lines.append(f"SELECTORS FOUND: {len(selectors)}")
            lines.append("=" * 100)
            for item in selectors:
                total += 1
                lines.extend(
                    [
                        f"[{total:04d}] kind={item.get('kind')} tag={item.get('tag')} text={item.get('text') or '(no text)'}",
                        f"       id={item.get('id') or '(none)'} name={item.get('name') or '(none)'} type={item.get('type') or '(none)'} role={item.get('role') or '(none)'}",
                        f"       css={item.get('css') or '(none)'}",
                        f"       xpath={item.get('xpath') or '(none)'}",
                        f"       href={item.get('href') or '(none)'} action={item.get('action') or '(none)'}",
                        "",
                    ]
                )
        lines.insert(2, f"Total selectors: {total}")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _locator_for_selector(self, page: Page, item: dict):
        xpath = item.get("xpath") or ""
        css = item.get("css") or ""
        if xpath:
            return page.locator(f"xpath={xpath}").first
        if css:
            return page.locator(css).first
        return None

    def _test_selector_inventory(
        self,
        page: Page,
        report: QARunReport,
        screenshots_dir: str,
        page_url: str,
        selectors: list[dict],
    ) -> None:
        by_kind: dict[str, int] = {}
        for item in selectors:
            kind = item.get("kind") or "unknown"
            by_kind[kind] = by_kind.get(kind, 0) + 1
        detail = ", ".join(f"{kind}={count}" for kind, count in sorted(by_kind.items())) or "No selectors found"
        self._add_case(
            report,
            page,
            screenshots_dir,
            "Selector inventory extraction",
            f"1. Inspect DOM\n2. Extract XPath, ID, CSS and metadata for UI elements\nPage: {page_url}",
            "Relevant selectors should be extracted for functional coverage",
            f"Selectors found: {len(selectors)} ({detail})",
            len(selectors) > 0,
        )

    def _test_headings_from_selectors(
        self,
        page: Page,
        report: QARunReport,
        screenshots_dir: str,
        page_url: str,
        selectors: list[dict],
    ) -> None:
        headings = [item for item in selectors if item.get("kind") == "heading"]
        self._add_case(
            report,
            page,
            screenshots_dir,
            "Heading verification",
            f"1. Extract heading selectors\n2. Verify heading text and visibility\nPage: {page_url}",
            "Page should expose visible headings with readable text",
            f"Headings found: {len(headings)}",
            len(headings) > 0,
        )
        for item in headings[: self.max_controls_per_type]:
            locator = self._locator_for_selector(page, item)
            try:
                visible = locator.is_visible(timeout=1500) if locator else False
                text = item.get("text") or ""
                self._add_case(
                    report,
                    page,
                    screenshots_dir,
                    "Heading visibility",
                    f"1. Locate heading with XPath/CSS\nXPath: {item.get('xpath')}\nCSS: {item.get('css')}\nPage: {page_url}",
                    "Heading should be visible and contain readable text",
                    f"Visible={visible}, text={text or '(empty)'}",
                    visible and bool(text.strip()),
                )
            except Exception as exc:
                self._add_case(
                    report,
                    page,
                    screenshots_dir,
                    "Heading visibility",
                    f"1. Locate heading with selector\nXPath: {item.get('xpath')}\nPage: {page_url}",
                    "Heading should be visible",
                    f"Heading verification failed: {str(exc)[:180]}",
                    False,
                )

    def _test_clickable_selectors(
        self,
        page: Page,
        report: QARunReport,
        screenshots_dir: str,
        page_url: str,
        selectors: list[dict],
        base_host: str,
    ) -> None:
        clickable_kinds = {"link", "button", "icon", "clickable"}
        clickables = [item for item in selectors if item.get("kind") in clickable_kinds]
        self._add_case(
            report, page, screenshots_dir,
            "Clickable selector coverage",
            f"1. Read selector inventory\n2. Count links, buttons, icons and clickable text\nPage: {page_url}",
            "Clickable UI elements should be available for sequential validation",
            f"Clickable selectors found: {len(clickables)}",
            len(clickables) > 0,
        )

        tested = 0
        for item in clickables[: self.max_links_per_page]:
            label = item.get("text") or item.get("id") or item.get("css") or "(no label)"
            href  = item.get("href") or ""

            # ── Skip already-tested elements ────────────────────────────────
            if self._is_tested(item):
                self._log_skip("Click Element", label)
                continue

            if href and href.startswith(("mailto:", "tel:", "javascript:")):
                self._mark_tested(item)
                continue

            target = self._clean_url(page_url, href) if href else ""
            if target and not self._same_host(target, base_host):
                self._add_case(
                    report, page, screenshots_dir,
                    "External link classification",
                    f"1. Inspect link selector\n2. Avoid leaving target domain\nXPath: {item.get('xpath')}\nHref: {href}",
                    "External links should be identified without breaking the test session",
                    "External link recorded and skipped for browser click",
                    True,
                )
                self._mark_tested(item)
                continue

            if not self._is_safe_action(label):
                self._add_case(
                    report, page, screenshots_dir,
                    "Clickable safety classification",
                    f"1. Inspect clickable selector\n2. Detect protected action keywords\nXPath: {item.get('xpath')}\nText: {label}",
                    "Protected actions should be recorded but not clicked automatically",
                    "Skipped click because label matched protected action keywords",
                    True,
                )
                self._mark_tested(item)
                continue

            try:
                locator = self._locator_for_selector(page, item)
                if locator is None:
                    raise RuntimeError("No XPath or CSS selector available")
                visible = locator.is_visible(timeout=1500)
                enabled = locator.is_enabled(timeout=1500)

                if not visible or not enabled:
                    # Distinguish: truly clickable by design but broken → FAIL
                    #              not clickable by design → PASS (no screenshot)
                    truly = self._is_truly_clickable(page, item)
                    self._add_case(
                        report, page, screenshots_dir,
                        "Clickable selector validation",
                        f"1. Locate clickable selector\nXPath: {item.get('xpath')}\nCSS: {item.get('css')}\nPage: {page_url}",
                        "Clickable element should be visible and enabled",
                        f"Visible={visible}, enabled={enabled} — {'clickable by design but not responding' if truly else 'not clickable by design, skipped'}",
                        not truly,  # FAIL only when element was truly meant to be clicked
                    )
                    self._mark_tested(item)
                    continue

                before_url = page.url
                locator.click(timeout=5000, trial=True)
                locator.click(timeout=5000, no_wait_after=True)
                page.wait_for_timeout(800)
                tested += 1
                after_url = page.url
                self._mark_tested(item)

                self._add_case(
                    report, page, screenshots_dir,
                    "Sequential clickable interaction",
                    f"1. Locate element by XPath/CSS\n2. Click element\nXPath: {item.get('xpath')}\nCSS: {item.get('css')}\nText: {label}\nPage: {page_url}",
                    "Clickable element should respond without browser automation failure",
                    f"Clicked successfully. URL before={before_url}, after={after_url}",
                    True,
                )

                # ── Validate navigated page then return ─────────────────────
                if after_url != page_url and self._same_host(after_url, base_host):
                    try:
                        title = page.title() or ""
                        ready = page.evaluate("() => document.readyState") == "complete"
                        self._add_case(
                            report, page, screenshots_dir,
                            "Navigated page validation",
                            f"1. Navigate via link click\n2. Validate destination page\nPage: {after_url}",
                            "Destination page should load with a valid title",
                            f"Loaded={ready}, title={title or '(empty)'}",
                            ready and bool(title.strip()),
                        )
                    except Exception:
                        pass
                    self._goto(page, page_url)

            except Exception as exc:
                truly = self._is_truly_clickable(page, item)
                self._add_case(
                    report, page, screenshots_dir,
                    "Sequential clickable interaction",
                    f"1. Locate element by XPath/CSS\n2. Click element\nXPath: {item.get('xpath')}\nCSS: {item.get('css')}\nText: {label}\nPage: {page_url}",
                    "Clickable element should be locatable and clickable",
                    f"Click failed: {str(exc)[:180]}",
                    not truly,  # FAIL only for elements with clickable intent
                )
                self._mark_tested(item)
                try:
                    if page.url != page_url:
                        self._goto(page, page_url)
                except Exception:
                    pass

        self._add_case(
            report, page, screenshots_dir,
            "Sequential clickable interaction summary",
            f"1. Use extracted selectors one by one\n2. Validate click behavior\nPage: {page_url}",
            "At least one safe clickable selector should be tested when clickables exist",
            f"Safe clickables tested: {tested}",
            tested > 0 or len(clickables) == 0,
        )

    # ── Interactive login credential handling ──────────────────────────────

    def _detect_login_page(self, page: Page) -> tuple[bool, bool]:
        """Return (has_password_field, has_user_field) for the current page."""
        try:
            pw_count = page.locator("input[type='password']:visible").count()
        except Exception:
            pw_count = 0
        has_password = pw_count > 0

        user_selector = (
            "input[type='email']:visible, "
            "input[name*='user' i]:visible, input[name*='login' i]:visible, "
            "input[name*='email' i]:visible, "
            "input[placeholder*='email' i]:visible, input[placeholder*='username' i]:visible"
        )
        try:
            user_count = page.locator(user_selector).count()
        except Exception:
            user_count = 0
        has_user = user_count > 0
        return has_password, has_user

    def _handle_login_credentials(
        self,
        page: Page,
        report: QARunReport,
        screenshots_dir: str,
        page_url: str,
    ) -> bool:
        """If the page looks like a login page, prompt for credentials,
        fill the form, and submit it.  Returns True when a login was attempted.

        Credentials are NEVER sourced from the browser or any stored file;
        the operator must type them interactively in the terminal.
        """
        has_password, has_user = self._detect_login_page(page)
        if not (has_password and has_user):
            return False

        print("\n" + "─" * 60)
        print("  🔐  Login page detected!")
        print(f"  URL: {page_url}")
        print("  Enter credentials to test the authenticated session.")
        print("  (Press Enter without typing to skip login and continue)")
        print("─" * 60)

        username = input("  Username / Email : ").strip()
        password = getpass.getpass("  Password         : ").strip()

        if not username or not password:
            # Operator chose to skip — record as informational
            self._add_case(
                report, page, screenshots_dir,
                "Login credential entry",
                f"1. Detect login page\n2. Prompt operator for credentials\nPage: {page_url}",
                "Operator should enter credentials to test authenticated session",
                "Operator skipped credential entry — continuing without login",
                True,
            )
            return False

        # ── Fill username / email ────────────────────────────────────────────
        user_selector = (
            "input[type='email']:visible, "
            "input[name*='user' i]:visible, input[name*='login' i]:visible, "
            "input[name*='email' i]:visible, "
            "input[placeholder*='email' i]:visible, input[placeholder*='username' i]:visible"
        )
        try:
            user_field = page.locator(user_selector).first
            user_field.fill(username, timeout=5000)
        except Exception as exc:
            self._add_case(
                report, page, screenshots_dir,
                "Login credential entry",
                f"1. Locate username/email field\n2. Fill with provided value\nPage: {page_url}",
                "Username/email field should accept text input",
                f"Could not fill username field: {str(exc)[:180]}",
                False,
            )
            return False

        # ── Fill password ────────────────────────────────────────────────────
        try:
            pw_field = page.locator("input[type='password']:visible").first
            pw_field.fill(password, timeout=5000)
        except Exception as exc:
            self._add_case(
                report, page, screenshots_dir,
                "Login credential entry",
                f"1. Locate password field\n2. Fill with provided value\nPage: {page_url}",
                "Password field should accept text input",
                f"Could not fill password field: {str(exc)[:180]}",
                False,
            )
            return False

        # ── Click submit / login button ──────────────────────────────────────
        submit_selector = (
            "button[type='submit']:visible, "
            "input[type='submit']:visible, "
            "button:text-matches('(log in|login|sign in|signin|submit)', 'i'):visible"
        )
        try:
            before_url = page.url
            submit_btn = page.locator(submit_selector).first
            submit_btn.click(timeout=8000)
            # Wait for navigation or dynamic content
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                page.wait_for_timeout(2000)

            after_url = page.url
            # Detect success: URL changed OR password field gone
            has_pw_after, _ = self._detect_login_page(page)
            login_success = (after_url != before_url) or (not has_pw_after)

            self._add_case(
                report, page, screenshots_dir,
                "Login credential entry",
                f"1. Detect login page\n2. Fill username and password\n3. Click submit\nPage: {page_url}",
                "Login form should accept credentials and navigate to authenticated area",
                f"Login {'succeeded' if login_success else 'may have failed'}. "
                f"URL before={before_url}, after={after_url}, "
                f"password field still visible={has_pw_after}",
                login_success,
            )
            return True

        except Exception as exc:
            self._add_case(
                report, page, screenshots_dir,
                "Login credential entry",
                f"1. Locate submit button\n2. Click to log in\nPage: {page_url}",
                "Login form should submit without automation error",
                f"Submit failed: {str(exc)[:180]}",
                False,
            )
            return False

    def _test_login_flow(
        self,
        page: Page,
        report: QARunReport,
        screenshots_dir: str,
        page_url: str,
        selectors: list[dict],
    ) -> None:
        login_candidates = [
            item for item in selectors
            if re.search(r"\b(log in|login|sign in|signin|account)\b", item.get("text") or "", re.I)
            or re.search(r"(login|signin|account)", item.get("href") or "", re.I)
            or re.search(r"(login|signin|account)", item.get("id") or "", re.I)
        ]
        has_password = any(
            (item.get("kind") == "input" and (item.get("type") or "").lower() == "password")
            for item in selectors
        )
        self._add_case(
            report,
            page,
            screenshots_dir,
            "Login page discovery",
            f"1. Inspect selectors for login/sign-in/account controls\n2. Detect password inputs\nPage: {page_url}",
            "Login controls or password fields should be detected when login is available",
            f"Login candidates={len(login_candidates)}, password fields={has_password}",
            len(login_candidates) > 0 or has_password,
        )

        if has_password:
            self._test_inputs(page, report, screenshots_dir, page_url)
            self._test_forms(page, report, screenshots_dir, page_url)
            return

        for item in login_candidates[:3]:
            try:
                locator = self._locator_for_selector(page, item)
                if locator is None:
                    continue
                before_url = page.url
                locator.click(timeout=5000, no_wait_after=True)
                page.wait_for_timeout(1500)
                password_count = page.locator("input[type='password']:visible").count()
                user_count = page.locator(
                    "input[type='email']:visible, input[name*='user' i]:visible, "
                    "input[name*='login' i]:visible, input[placeholder*='email' i]:visible, "
                    "input[placeholder*='username' i]:visible"
                ).count()
                self._add_case(
                    report,
                    page,
                    screenshots_dir,
                    "Login interaction",
                    f"1. Click login/account selector\n2. Verify login fields\nXPath: {item.get('xpath')}\nText: {item.get('text')}\nPage: {page_url}",
                    "Login action should reveal username/email and password controls or navigate to login page",
                    f"URL before={before_url}, after={page.url}, user fields={user_count}, password fields={password_count}",
                    password_count > 0 or "login" in page.url.lower() or "signin" in page.url.lower(),
                )
                if password_count > 0 or user_count > 0:
                    self._test_inputs(page, report, screenshots_dir, page.url)
                    self._test_forms(page, report, screenshots_dir, page.url)
                self._goto(page, page_url)
                break
            except Exception as exc:
                self._add_case(
                    report,
                    page,
                    screenshots_dir,
                    "Login interaction",
                    f"1. Click login/account selector\nXPath: {item.get('xpath')}\nText: {item.get('text')}\nPage: {page_url}",
                    "Login control should be clickable and expose login UI",
                    f"Login test failed: {str(exc)[:180]}",
                    False,
                )

    def _record_console_and_network(self, page: Page, report: QARunReport, screenshots_dir: str, page_url: str) -> None:
        """Capture console errors and failed network requests for the current page.

        NOTE: Listeners are attached to the existing page BEFORE navigation so
        that errors emitted during load are captured correctly.  We navigate to
        a fresh copy of page_url rather than reloading to avoid disturbing any
        authenticated session cookies while still triggering a clean resource load.
        """
        console_errors: list[str] = []
        failed_requests: list[str] = []

        # Register listeners BEFORE navigating so early-load errors are captured
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("requestfailed", lambda req: failed_requests.append(req.url))

        try:
            # Navigate to the same URL rather than reload to preserve session state
            page.goto(page_url, wait_until="domcontentloaded", timeout=self.timeout)
            page.wait_for_timeout(1500)
        except Exception:
            pass

        self._add_case(
            report,
            page,
            screenshots_dir,
            "JavaScript console health",
            f"1. Load page\n2. Capture browser console errors\nPage: {page_url}",
            "Page should not emit JavaScript console errors",
            "No console errors" if not console_errors else "; ".join(console_errors[:3])[:300],
            len(console_errors) == 0,
        )
        self._add_case(
            report,
            page,
            screenshots_dir,
            "Network resource health",
            f"1. Load page\n2. Capture failed network requests\nPage: {page_url}",
            "Page resources should load without request failures",
            "No failed requests" if not failed_requests else "; ".join(failed_requests[:3])[:300],
            len(failed_requests) == 0,
        )

    def _test_links(self, page: Page, report: QARunReport, screenshots_dir: str, page_url: str, base_host: str) -> None:
        try:
            links = page.locator("a[href]:visible").evaluate_all(
                """els => els.map(a => ({
                    href: a.getAttribute('href') || '',
                    text: (a.innerText || a.getAttribute('aria-label') || '').trim()
                }))"""
            )
        except Exception:
            links = []

        self._add_case(
            report, page, screenshots_dir,
            "Visible link discovery",
            f"1. Find visible links on page\nPage: {page_url}",
            "At least one visible link should be available",
            f"Visible links found: {len(links)}",
            len(links) > 0,
        )

        checked = 0
        for link in links[: self.max_links_per_page]:
            href = (link.get("href") or "").strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            target = self._clean_url(page_url, href)
            if not self._same_host(target, base_host):
                continue

            # ── Skip already-checked URLs ────────────────────────────────────
            link_key = f"link::{target}"
            if link_key in self._tested_elements:
                text = (link.get("text") or target)[:60]
                self._log_skip("Validate Link", text)
                continue
            self._tested_elements.add(link_key)

            checked += 1
            try:
                response = page.request.get(target, timeout=10000, max_redirects=3)
                ok = response.status < 400
                self._add_case(
                    report, page, screenshots_dir,
                    "Internal link validation",
                    f"1. Resolve internal link\n2. Request target URL\nLink: {target}",
                    "Internal link should return HTTP status below 400",
                    f"HTTP status: {response.status}",
                    ok,
                )
            except Exception as exc:
                self._add_case(
                    report, page, screenshots_dir,
                    "Internal link validation",
                    f"1. Resolve internal link\n2. Request target URL\nLink: {target}",
                    "Internal link should be reachable",
                    f"Request failed: {str(exc)[:180]}",
                    False,
                )

        if checked == 0:
            self._add_case(
                report, page, screenshots_dir,
                "Internal link validation",
                f"1. Collect same-domain links\nPage: {page_url}",
                "At least one internal link should be available for validation",
                "No same-domain links available",
                False,
            )

    def _test_inputs(self, page: Page, report: QARunReport, screenshots_dir: str, page_url: str) -> None:
        selector = "input:visible, textarea:visible"
        try:
            total = page.locator(selector).count()
        except Exception:
            total = 0

        self._add_case(
            report,
            page,
            screenshots_dir,
            "Input field discovery",
            f"1. Find visible input and textarea fields\nPage: {page_url}",
            "Input fields should be detected when present",
            f"Visible input/textarea fields found: {total}",
            True,
        )

        for idx in range(min(total, self.max_controls_per_type)):
            locator = page.locator(selector).nth(idx)
            try:
                input_type = (locator.get_attribute("type", timeout=1000) or "").lower()
                name = locator.get_attribute("name", timeout=1000) or locator.get_attribute("id", timeout=1000) or f"field-{idx + 1}"
                if input_type in ("hidden", "file", "submit", "button", "reset", "image"):
                    continue
                if input_type not in TEXT_INPUT_TYPES:
                    continue
                sample = self._sample_value(input_type, name)
                locator.fill(sample, timeout=5000)
                value = locator.input_value(timeout=1000)
                self._add_case(
                    report,
                    page,
                    screenshots_dir,
                    "Input field interaction",
                    f"1. Locate field: {name}\n2. Fill sample value\n3. Verify field value\nPage: {page_url}",
                    "Field should accept typed input and preserve entered value",
                    f"Input type={input_type or 'text'}, value accepted={value == sample}",
                    value == sample,
                )
            except Exception as exc:
                self._add_case(
                    report,
                    page,
                    screenshots_dir,
                    "Input field interaction",
                    f"1. Locate input #{idx + 1}\n2. Fill sample value\nPage: {page_url}",
                    "Field should be fillable",
                    f"Interaction failed: {str(exc)[:180]}",
                    False,
                )

    def _sample_value(self, input_type: str, name: str) -> str:
        hint = (name or "").lower()
        if input_type == "email" or "email" in hint:
            return "qa-test@example.com"
        if input_type == "tel" or "phone" in hint or "mobile" in hint:
            return "9876543210"
        if input_type == "url" or "website" in hint:
            return "https://example.com"
        if input_type == "number" or "age" in hint or "qty" in hint:
            return "1"
        if input_type == "password":
            return "QaTest@12345"
        if input_type == "search" or "search" in hint:
            return "test"
        return "QA automated test"

    def _test_choices(self, page: Page, report: QARunReport, screenshots_dir: str, page_url: str) -> None:
        checkbox_selector = "input[type='checkbox']:visible"
        radio_selector = "input[type='radio']:visible"

        for label, selector in (("Checkbox", checkbox_selector), ("Radio button", radio_selector)):
            try:
                total = page.locator(selector).count()
            except Exception:
                total = 0
            self._add_case(
                report,
                page,
                screenshots_dir,
                f"{label} discovery",
                f"1. Find visible {label.lower()} controls\nPage: {page_url}",
                f"{label} controls should be detected when present",
                f"Visible {label.lower()} controls found: {total}",
                True,
            )

            for idx in range(min(total, self.max_controls_per_type)):
                locator = page.locator(selector).nth(idx)
                try:
                    locator.check(timeout=5000)
                    checked = locator.is_checked(timeout=1000)
                    name = locator.get_attribute("name", timeout=1000) or f"{label.lower()}-{idx + 1}"
                    self._add_case(
                        report,
                        page,
                        screenshots_dir,
                        f"{label} interaction",
                        f"1. Locate {label.lower()}: {name}\n2. Select it\n3. Verify selected state\nPage: {page_url}",
                        f"{label} should be selectable",
                        f"Selected state: {checked}",
                        checked,
                    )
                except Exception as exc:
                    self._add_case(
                        report,
                        page,
                        screenshots_dir,
                        f"{label} interaction",
                        f"1. Locate {label.lower()} #{idx + 1}\n2. Select it\nPage: {page_url}",
                        f"{label} should be selectable",
                        f"Interaction failed: {str(exc)[:180]}",
                        False,
                    )

    def _test_selects(self, page: Page, report: QARunReport, screenshots_dir: str, page_url: str) -> None:
        selector = "select:visible"
        try:
            total = page.locator(selector).count()
        except Exception:
            total = 0

        self._add_case(
            report,
            page,
            screenshots_dir,
            "Dropdown discovery",
            f"1. Find visible select dropdowns\nPage: {page_url}",
            "Dropdown controls should be detected when present",
            f"Visible dropdowns found: {total}",
            True,
        )

        for idx in range(min(total, self.max_controls_per_type)):
            locator = page.locator(selector).nth(idx)
            try:
                options = locator.locator("option:not(:disabled)").evaluate_all(
                    "els => els.map(o => o.value).filter(v => v !== '')"
                )
                if not options:
                    options = locator.locator("option:not(:disabled)").evaluate_all("els => els.map(o => o.value)")
                if not options:
                    raise RuntimeError("No selectable options found")
                selected = locator.select_option(options[0], timeout=5000)
                current = locator.input_value(timeout=1000)
                name = locator.get_attribute("name", timeout=1000) or f"dropdown-{idx + 1}"
                self._add_case(
                    report,
                    page,
                    screenshots_dir,
                    "Dropdown interaction",
                    f"1. Locate dropdown: {name}\n2. Select first available option\n3. Verify selected value\nPage: {page_url}",
                    "Dropdown should allow selecting an available option",
                    f"Selected={selected}, current value={current}",
                    bool(selected) and current in selected,
                )
            except Exception as exc:
                self._add_case(
                    report,
                    page,
                    screenshots_dir,
                    "Dropdown interaction",
                    f"1. Locate dropdown #{idx + 1}\n2. Select an option\nPage: {page_url}",
                    "Dropdown should allow option selection",
                    f"Interaction failed: {str(exc)[:180]}",
                    False,
                )

    def _test_buttons(self, page: Page, report: QARunReport, screenshots_dir: str, page_url: str) -> None:
        selector = "button:visible, [role='button']:visible, input[type='button']:visible, input[type='submit']:visible"
        try:
            total = page.locator(selector).count()
        except Exception:
            total = 0

        self._add_case(
            report, page, screenshots_dir,
            "Button discovery",
            f"1. Find visible buttons\nPage: {page_url}",
            "At least one button-like control should be visible on interactive pages",
            f"Visible buttons found: {total}",
            total > 0,
        )

        tested = 0
        for idx in range(min(total, self.max_controls_per_type)):
            locator = page.locator(selector).nth(idx)
            label = self._safe_label(locator)

            # ── Skip already-tested buttons ──────────────────────────────────
            btn_key = self._btn_key(page_url, label)
            if btn_key in self._tested_elements:
                self._log_skip("Click Button", label)
                continue

            if not self._is_safe_action(label):
                self._add_case(
                    report, page, screenshots_dir,
                    "Button safety classification",
                    f"1. Locate button: {label}\n2. Check if action appears safe to click\nPage: {page_url}",
                    "Potentially destructive or transactional controls should not be clicked automatically",
                    "Skipped automatic click because label matched a protected action",
                    True,
                )
                self._tested_elements.add(btn_key)
                continue

            try:
                enabled = locator.is_enabled(timeout=1000)
                if not enabled:
                    # A disabled button is an expected state (e.g. submit before
                    # filling a form).  Record as informational PASS, not FAIL.
                    self._add_case(
                        report, page, screenshots_dir,
                        "Button interaction",
                        f"1. Locate button: {label}\n2. Verify enabled state\nPage: {page_url}",
                        "Disabled button state should be correctly represented in DOM",
                        "Button is disabled (expected — no click attempted)",
                        True,
                    )
                    self._tested_elements.add(btn_key)
                    continue

                before_url = page.url
                locator.click(timeout=5000, trial=True)
                locator.click(timeout=5000, no_wait_after=True)
                page.wait_for_timeout(800)
                tested += 1
                self._tested_elements.add(btn_key)
                self._add_case(
                    report, page, screenshots_dir,
                    "Button interaction",
                    f"1. Locate button: {label}\n2. Click the button\n3. Confirm no browser automation error\nPage: {page_url}",
                    "Button should be clickable without automation errors",
                    f"Clicked successfully. URL before={before_url}, after={page.url}",
                    True,
                )
                if page.url != before_url:
                    self._goto(page, page_url)
            except Exception as exc:
                self._tested_elements.add(btn_key)
                self._add_case(
                    report, page, screenshots_dir,
                    "Button interaction",
                    f"1. Locate button: {label}\n2. Click the button\nPage: {page_url}",
                    "Button should be clickable without throwing an error",
                    f"Click failed: {str(exc)[:180]}",
                    False,
                )

        if total > 0 and tested == 0:
            self._add_case(
                report,
                page,
                screenshots_dir,
                "Button interaction coverage",
                f"1. Review visible buttons\nPage: {page_url}",
                "At least one safe button should be available for click testing, unless all are protected actions",
                "No safe clickable button was tested",
                True,
            )

    def _test_forms(self, page: Page, report: QARunReport, screenshots_dir: str, page_url: str) -> None:
        try:
            total = page.locator("form").count()
        except Exception:
            total = 0

        self._add_case(
            report,
            page,
            screenshots_dir,
            "Form discovery",
            f"1. Detect form elements\nPage: {page_url}",
            "Forms should be detected when present",
            f"Forms found: {total}",
            True,
        )

        for idx in range(min(total, self.max_controls_per_type)):
            form = page.locator("form").nth(idx)
            try:
                fields = form.locator("input:visible, textarea:visible, select:visible").count()
                submit_buttons = form.locator("button[type='submit']:visible, input[type='submit']:visible, button:not([type]):visible").count()
                method = (form.get_attribute("method", timeout=1000) or "GET").upper()
                action = form.get_attribute("action", timeout=1000) or "(same page)"
                self._add_case(
                    report,
                    page,
                    screenshots_dir,
                    "Form structure validation",
                    f"1. Inspect form #{idx + 1}\n2. Count fields and submit controls\nPage: {page_url}",
                    "Form should contain fields and a submit action",
                    f"Fields={fields}, submit controls={submit_buttons}, method={method}, action={action}",
                    fields > 0 and submit_buttons > 0,
                )

                if fields == 0 or submit_buttons == 0:
                    continue

                self._fill_form(form)
                submit = form.locator("button[type='submit']:visible, input[type='submit']:visible, button:not([type]):visible").first
                label = self._safe_label(submit)
                if not self._is_safe_action(label):
                    self._add_case(
                        report,
                        page,
                        screenshots_dir,
                        "Form submit safety classification",
                        f"1. Fill form #{idx + 1}\n2. Inspect submit label: {label}\nPage: {page_url}",
                        "Potentially destructive or transactional forms should not be submitted automatically",
                        "Skipped submit because label matched a protected action",
                        True,
                    )
                    continue

                before_url = page.url
                submit.click(timeout=5000, no_wait_after=True)
                page.wait_for_timeout(1200)
                validation_count = page.locator(
                    "[aria-invalid='true'], .error:visible, .invalid-feedback:visible, "
                    "[role='alert']:visible, input:invalid, textarea:invalid, select:invalid"
                ).count()
                self._add_case(
                    report,
                    page,
                    screenshots_dir,
                    "Form submission interaction",
                    f"1. Fill form #{idx + 1} with sample data\n2. Submit form\n3. Check response/validation\nPage: {page_url}",
                    "Form should submit or display validation without automation failure",
                    f"Submitted successfully. URL before={before_url}, after={page.url}, validation indicators={validation_count}",
                    True,
                )
                if page.url != before_url:
                    self._goto(page, page_url)
            except Exception as exc:
                self._add_case(
                    report,
                    page,
                    screenshots_dir,
                    "Form submission interaction",
                    f"1. Fill form #{idx + 1}\n2. Submit or validate the form\nPage: {page_url}",
                    "Form should accept sample input and submit or validate cleanly",
                    f"Form interaction failed: {str(exc)[:180]}",
                    False,
                )

    def _fill_form(self, form) -> None:
        """Fill all visible text-like inputs in a form with safe sample data.

        Each field is wrapped in its own try/except so a single broken field
        (e.g. covered by an overlay) cannot abort the entire fill pass.
        """
        fields = form.locator("input:visible, textarea:visible")
        for idx in range(min(fields.count(), self.max_controls_per_type)):
            try:
                field = fields.nth(idx)
                input_type = (field.get_attribute("type", timeout=1000) or "").lower()
                if input_type in ("hidden", "file", "submit", "button", "reset", "image", "checkbox", "radio"):
                    continue
                if input_type not in TEXT_INPUT_TYPES:
                    continue
                name = field.get_attribute("name", timeout=1000) or field.get_attribute("id", timeout=1000) or ""
                field.fill(self._sample_value(input_type, name), timeout=5000)
            except Exception:
                # Skip this specific field and move on
                continue

        checks = form.locator("input[type='checkbox']:visible")
        for idx in range(min(checks.count(), 3)):
            try:
                checks.nth(idx).check(timeout=3000)
            except Exception:
                continue

        radios = form.locator("input[type='radio']:visible")
        if radios.count() > 0:
            try:
                radios.first.check(timeout=3000)
            except Exception:
                pass

        selects = form.locator("select:visible")
        for idx in range(min(selects.count(), 3)):
            select = selects.nth(idx)
            options = select.locator("option:not(:disabled)").evaluate_all(
                "els => els.map(o => o.value).filter(v => v !== '')"
            )
            if options:
                select.select_option(options[0], timeout=3000)

    def _test_page_structure(self, page: Page, report: QARunReport, screenshots_dir: str, page_url: str, response) -> None:
        status_code = response.status if response else 0
        title = ""
        try:
            title = page.title() or ""
        except Exception:
            pass

        self._add_case(
            report,
            page,
            screenshots_dir,
            "Page load validation",
            f"1. Open page\n2. Wait for DOM content\nPage: {page_url}",
            "Page should load successfully with HTTP status below 400",
            f"HTTP status: {status_code}",
            bool(response and status_code < 400),
        )
        self._add_case(
            report,
            page,
            screenshots_dir,
            "Page title validation",
            f"1. Read document title\nPage: {page_url}",
            "Page title should not be empty",
            f"Title: {title if title else '(empty)'}",
            bool(title.strip()),
        )

        ui_checks = [
            ("Header visibility", "header"),
            ("Main content visibility", "main, [role='main']"),
            ("Navigation visibility", "nav, [role='navigation']"),
            ("Footer visibility", "footer"),
        ]
        for label, selector in ui_checks:
            try:
                visible = page.locator(selector).first.is_visible(timeout=1000)
            except Exception:
                visible = False
            self._add_case(
                report,
                page,
                screenshots_dir,
                label,
                f"1. Query visible UI element by selector: {selector}\nPage: {page_url}",
                f"{label.split()[0]} should be visible on page",
                "Visible" if visible else "Not visible",
                visible,
            )

    def run(self, url: str, screenshots_dir: str = "screenshots") -> QARunReport:
        """Run the full QA suite against *url*.

        Login detection:
          If the landing page is identified as a login page the operator is
          prompted once for credentials.  The authenticated session is then
          used for all subsequent page visits so authenticated-only pages are
          included in the crawl.
        """
        url = self._normalize_url(url)
        started = datetime.now().isoformat()
        self._counter = 1
        self._logger.reset()
        self._tested_elements = set()
        selectors_by_page: dict[str, list[dict]] = {}

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            context = browser.new_context(
                viewport={"width": 1366, "height": 768},
                screen={"width": 1366, "height": 768},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()

            response = self._goto(page, url)
            report = QARunReport(
                url=url,
                final_url=page.url,
                started_at=started,
                finished_at="",
                selector_file_path=self._selector_report_path(page.url),
            )

            # ── Login page detection & credential handling ───────────────────
            # Done ONCE on the landing page before page discovery so the
            # authenticated session covers all crawled pages.
            self._handle_login_credentials(page, report, screenshots_dir, page.url)

            base_host = urlparse(page.url).netloc
            pages = self._discover_pages(page, page.url)

            # Print execution header now that we know page count
            self._logger.start(url, len(pages))

            for i, page_url in enumerate(pages, start=1):
                self._logger.section(f"Page {i}/{len(pages)}: {page_url}")
                try:
                    page = context.new_page()
                    response = self._goto(page, page_url)
                    report.pages_tested += 1
                    selectors = self._extract_selectors(page, page_url)
                    selectors_by_page[page_url] = selectors

                    self._test_page_structure(page, report, screenshots_dir, page_url, response)
                    self._test_selector_inventory(page, report, screenshots_dir, page_url, selectors)
                    self._test_headings_from_selectors(page, report, screenshots_dir, page_url, selectors)
                    self._record_console_and_network(page, report, screenshots_dir, page_url)
                    self._test_links(page, report, screenshots_dir, page_url, base_host)
                    self._test_clickable_selectors(page, report, screenshots_dir, page_url, selectors, base_host)
                    self._test_inputs(page, report, screenshots_dir, page_url)
                    self._test_choices(page, report, screenshots_dir, page_url)
                    self._test_selects(page, report, screenshots_dir, page_url)
                    self._test_buttons(page, report, screenshots_dir, page_url)
                    self._test_forms(page, report, screenshots_dir, page_url)
                    self._test_login_flow(page, report, screenshots_dir, page_url, selectors)
                except PlaywrightError as exc:
                    self._add_case(
                        report,
                        page,
                        screenshots_dir,
                        "Page automation failure",
                        f"1. Load and test page\nPage: {page_url}",
                        "Automation should complete page checks",
                        f"Automation failed: {str(exc)[:180]}",
                        False,
                    )
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass

            browser.close()

        self._write_selector_file(report.selector_file_path, selectors_by_page)
        report.finished_at = datetime.now().isoformat()

        # Print live execution summary to terminal
        self._logger.summary()

        return report
