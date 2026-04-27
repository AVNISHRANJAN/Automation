"""
error_tester.py — Error Handling Testing (Category 18)

Tests:
  - Custom 404 page (check a known-bad URL)
  - Error messages on invalid form input
  - Console errors on page load
  - Missing images (broken img src)
  - Failed resource loads
  - Generic vs informative error messages
  - HTTP error status detection
"""

from playwright.sync_api import Page
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin
import random
import string


@dataclass
class ErrorTestResult:
    category: str
    test: str
    passed: bool
    detail: str


@dataclass
class ErrorTestSummary:
    results: list[ErrorTestResult] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    broken_images: list[str] = field(default_factory=list)
    failed_resources: list[str] = field(default_factory=list)

    @property
    def passed(self): return [r for r in self.results if r.passed]
    @property
    def failed(self): return [r for r in self.results if not r.passed]


def run_error_tests(page: Page, base_url: str) -> ErrorTestSummary:
    summary = ErrorTestSummary()

    # ── Console errors ───────────────────────────────────────────────────────
    console_msgs = []
    page.on("console", lambda msg: console_msgs.append(msg) if msg.type == "error" else None)

    failed_resources = []
    page.on("requestfailed", lambda req: failed_resources.append(req.url))

    # Reload to capture fresh console/network errors
    try:
        page.reload(wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)
    except Exception:
        pass

    summary.console_errors = [m.text for m in console_msgs[:10]]
    summary.failed_resources = failed_resources[:10]

    summary.results.append(ErrorTestResult(
        category="Console",
        test="No JS console errors on page load",
        passed=len(console_msgs) == 0,
        detail=f"No console errors ✓" if len(console_msgs) == 0 else f"⚠️ {len(console_msgs)} console error(s): {'; '.join(m.text[:60] for m in console_msgs[:3])}",
    ))

    summary.results.append(ErrorTestResult(
        category="Network",
        test="No failed resource loads",
        passed=len(failed_resources) == 0,
        detail="All resources loaded ✓" if len(failed_resources) == 0 else f"⚠️ {len(failed_resources)} failed: {'; '.join(r[:60] for r in failed_resources[:3])}",
    ))

    # ── Broken images ────────────────────────────────────────────────────────
    try:
        broken = page.evaluate("""
            () => Array.from(document.images)
                .filter(img => !img.complete || img.naturalWidth === 0)
                .map(img => img.src)
                .slice(0, 10)
        """)
        summary.broken_images = broken
        summary.results.append(ErrorTestResult(
            category="Images",
            test="No broken images",
            passed=len(broken) == 0,
            detail=f"All images loaded ✓" if len(broken) == 0 else f"⚠️ {len(broken)} broken image(s): {'; '.join(b[:60] for b in broken[:3])}",
        ))
    except Exception:
        pass

    # ── Custom 404 page ──────────────────────────────────────────────────────
    try:
        rand_slug = "".join(random.choices(string.ascii_lowercase, k=12))
        notfound_url = urljoin(base_url, f"/{rand_slug}-notfound-test")
        resp = page.request.get(notfound_url, timeout=10000)
        status = resp.status

        if status == 404:
            body = resp.text()[:500].lower()
            is_custom = any(kw in body for kw in [
                "page not found", "404", "oops", "sorry", "doesn't exist",
                "not found", "went wrong", "missing", "lost",
            ])
            summary.results.append(ErrorTestResult(
                category="404 Page",
                test="Custom 404 page (not generic)",
                passed=is_custom,
                detail="Custom 404 page detected ✓" if is_custom else "Generic/blank 404 — no custom error page",
            ))
        elif status == 200:
            # Soft 404 — dangerous
            summary.results.append(ErrorTestResult(
                category="404 Page",
                test="Proper 404 status code (not soft-404)",
                passed=False,
                detail=f"⚠️ Soft 404 — returns HTTP 200 for non-existent pages (bad for SEO + UX)",
            ))
        else:
            summary.results.append(ErrorTestResult(
                category="404 Page",
                test="404 status for non-existent pages",
                passed=status in (404, 410),
                detail=f"HTTP {status} returned for invalid URL",
            ))
    except Exception as e:
        summary.results.append(ErrorTestResult(
            category="404 Page", test="Custom 404 check",
            passed=False, detail=f"Could not check 404 page: {str(e)[:60]}",
        ))

    # ── Form error messages ──────────────────────────────────────────────────
    error_msg_selectors = [
        '[class*="error" i]', '[class*="invalid" i]', '[role="alert"]',
        '[aria-invalid]', '.field-error', '.form-error', '.error-message',
        '[class*="validation" i]',
    ]
    error_elements = []
    for sel in error_msg_selectors:
        try:
            els = page.query_selector_all(f'{sel}:visible')
            error_elements.extend(els)
        except Exception:
            pass

    has_error_ui = len(error_elements) > 0
    # Even if none visible now, check if aria-invalid hooks exist
    aria_invalid_inputs = page.query_selector_all('[aria-invalid]')
    has_validation_hooks = len(aria_invalid_inputs) > 0

    summary.results.append(ErrorTestResult(
        category="Form Errors",
        test="Form error message elements present",
        passed=has_error_ui or has_validation_hooks,
        detail=f"Error UI found ({len(error_elements)} elements) ✓" if has_error_ui else ("aria-invalid hooks found ✓" if has_validation_hooks else "No visible error message containers (may appear after submit)"),
    ))

    # ── Generic vs specific error messages ──────────────────────────────────
    if has_error_ui:
        error_texts = []
        for el in error_elements[:5]:
            try:
                t = el.inner_text().strip()
                if t:
                    error_texts.append(t[:80])
            except Exception:
                pass
        generic_phrases = ["error", "invalid", "required", "please fill"]
        specific_phrases = ["email", "password", "name", "phone", "date", "must be", "at least", "format"]
        is_specific = any(sp in " ".join(error_texts).lower() for sp in specific_phrases)
        summary.results.append(ErrorTestResult(
            category="Form Errors",
            test="Error messages are specific (not generic)",
            passed=is_specific or len(error_texts) == 0,
            detail=f"Specific error messages ✓: {error_texts[:2]}" if is_specific else "Generic error messages only — be more descriptive",
        ))

    # ── Missing alt text on images (accessibility error) ────────────────────
    try:
        missing_alt = page.evaluate("""
            () => Array.from(document.images)
                .filter(img => !img.alt && img.naturalWidth > 0)
                .length
        """)
        total_imgs = page.evaluate("() => document.images.length")
        summary.results.append(ErrorTestResult(
            category="Accessibility",
            test="All images have alt text",
            passed=missing_alt == 0,
            detail=f"All {total_imgs} image(s) have alt text ✓" if missing_alt == 0 else f"⚠️ {missing_alt}/{total_imgs} images missing alt text",
        ))
    except Exception:
        pass

    # ── window.onerror / global error handler ────────────────────────────────
    try:
        has_error_handler = page.evaluate("""
            () => typeof window.onerror === 'function' || window.__errorHandlerRegistered === true
        """)
        summary.results.append(ErrorTestResult(
            category="JS Error Handling",
            test="Global JS error handler present",
            passed=has_error_handler,
            detail="window.onerror handler found ✓" if has_error_handler else "No global JS error handler (unhandled errors may be silent)",
        ))
    except Exception:
        pass

    return summary
