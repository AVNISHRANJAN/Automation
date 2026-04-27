"""
test_runner.py — Master orchestrator for all test categories

Runs all 11 test modules and returns a unified TestReport.
"""

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from dataclasses import dataclass, field
import time

from src.testers.form_tester       import run_form_tests,        FormTestSummary
from src.testers.nav_tester        import run_nav_tests,          NavTestSummary
from src.testers.auth_tester       import run_auth_tests,         AuthTestSummary
from src.testers.session_tester    import run_session_tests,      SessionTestSummary
from src.testers.search_tester     import run_search_tests,       SearchTestSummary
from src.testers.payment_tester    import run_payment_tests,      PaymentTestSummary
from src.testers.file_tester       import run_file_tests,         FileTestSummary
from src.testers.error_tester      import run_error_tests,        ErrorTestSummary
from src.testers.performance_tester import run_performance_tests, PerfTestSummary
from src.testers.security_tester   import run_security_tests,     SecurityTestSummary
from src.testers.compat_tester     import run_compat_tests,       CompatTestSummary


@dataclass
class TestReport:
    url: str
    final_url: str
    page_title: str
    scan_time_s: float

    form:        FormTestSummary    = field(default_factory=FormTestSummary)
    nav:         NavTestSummary     = field(default_factory=NavTestSummary)
    auth:        AuthTestSummary    = field(default_factory=AuthTestSummary)
    session:     SessionTestSummary = field(default_factory=SessionTestSummary)
    search:      SearchTestSummary  = field(default_factory=SearchTestSummary)
    payment:     PaymentTestSummary = field(default_factory=PaymentTestSummary)
    files:       FileTestSummary    = field(default_factory=FileTestSummary)
    errors:      ErrorTestSummary   = field(default_factory=ErrorTestSummary)
    performance: PerfTestSummary    = field(default_factory=PerfTestSummary)
    security:    SecurityTestSummary = field(default_factory=SecurityTestSummary)
    compat:      CompatTestSummary  = field(default_factory=CompatTestSummary)

    @property
    def all_results(self):
        return (
            self.form.results + self.nav.results + self.auth.results +
            self.session.results + self.search.results + self.payment.results +
            self.files.results + self.errors.results + self.performance.results +
            self.security.results + self.compat.results
        )

    @property
    def total_passed(self): return sum(1 for r in self.all_results if r.passed)
    @property
    def total_failed(self): return sum(1 for r in self.all_results if not r.passed)
    @property
    def total_tests(self): return len(self.all_results)
    @property
    def score(self): return round((self.total_passed / self.total_tests) * 100) if self.total_tests else 0


MODULES = [
    ("11. Form Testing",          "form"),
    ("12. Navigation Testing",    "nav"),
    ("13. Authentication Testing","auth"),
    ("14. Session Testing",       "session"),
    ("15. Search Testing",        "search"),
    ("16. Payment Testing",       "payment"),
    ("17. File Upload/Download",  "files"),
    ("18. Error Handling",        "errors"),
    ("19. Performance Testing",   "performance"),
    ("20. Security Testing",      "security"),
    ("21. Compatibility Testing", "compat"),
]


class TestRunner:
    def __init__(self, headless: bool = True, timeout: int = 20000):
        self.headless = headless
        self.timeout  = timeout

    def run(self, url: str) -> TestReport:
        if not url.startswith("http"):
            url = "https://" + url

        t0 = time.time()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
                page.wait_for_load_state("networkidle", timeout=8000)
            except PWTimeout:
                pass

            final_url  = page.url
            page_title = page.title()

            report = TestReport(
                url=url, final_url=final_url,
                page_title=page_title, scan_time_s=0,
            )

            runners = [
                ("11. Form Testing",           lambda: run_form_tests(page),                    "form"),
                ("12. Navigation Testing",     lambda: run_nav_tests(page, final_url),          "nav"),
                ("13. Authentication Testing", lambda: run_auth_tests(page, final_url),         "auth"),
                ("14. Session Testing",        lambda: run_session_tests(page),                 "session"),
                ("15. Search Testing",         lambda: run_search_tests(page),                  "search"),
                ("16. Payment Testing",        lambda: run_payment_tests(page),                 "payment"),
                ("17. File Upload/Download",   lambda: run_file_tests(page),                    "files"),
                ("18. Error Handling",         lambda: run_error_tests(page, final_url),        "errors"),
                ("19. Performance Testing",    lambda: run_performance_tests(page),             "performance"),
                ("20. Security Testing",       lambda: run_security_tests(page, final_url),     "security"),
                ("21. Compatibility Testing",  lambda: run_compat_tests(page),                  "compat"),
            ]

            for label, runner_fn, attr in runners:
                print(f"  ⏳ {label}...", end="", flush=True)
                try:
                    result = runner_fn()
                    setattr(report, attr, result)
                    # Defensive access: some testers may return partial summaries
                    passed = len(getattr(result, "passed", []) or [])
                    total  = len(getattr(result, "results", []) or [])
                    print(f" ✅ {passed}/{total}")
                except Exception as e:
                    print(f" ❌ Error: {e}")

            browser.close()

        report.scan_time_s = round(time.time() - t0, 2)
        return report
