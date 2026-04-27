"""qa_logger.py — Real-time step-by-step console logger for QA runner.

Prints a numbered, coloured execution log to stdout as each test step
runs.  Screenshots are announced inline immediately after capture.
"""

import re
import sys

# ── ANSI colours (auto-disabled when stdout is not a TTY) ──────────────────
_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_CYAN   = "\033[96m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_RESET  = "\033[0m"

# ── Scenario → human action label ─────────────────────────────────────────
_ACTION_MAP: dict[str, str] = {
    "page load validation":                   "Open URL",
    "page title validation":                  "Page Title Validation",
    "header visibility":                      "Header Visibility",
    "main content visibility":                "Main Content Visibility",
    "navigation visibility":                  "Navigation Visibility",
    "footer visibility":                      "Footer Visibility",
    "visible link discovery":                 "Discover Links",
    "internal link validation":               "Validate Link",
    "input field discovery":                  "Discover Input Fields",
    "input field interaction":                "Fill Input Field",
    "button discovery":                       "Discover Buttons",
    "button interaction":                     "Click Button",
    "button safety classification":           "Skip Protected Button",
    "button interaction coverage":            "Button Coverage Check",
    "form discovery":                         "Discover Forms",
    "form structure validation":              "Validate Form Structure",
    "form submission interaction":            "Submit Form",
    "form submit safety classification":      "Skip Protected Form Submit",
    "checkbox discovery":                     "Discover Checkboxes",
    "checkbox interaction":                   "Click Checkbox",
    "radio button discovery":                 "Discover Radio Buttons",
    "radio button interaction":               "Select Radio Button",
    "dropdown discovery":                     "Discover Dropdowns",
    "dropdown interaction":                   "Open Dropdown",
    "selector inventory extraction":          "Extract UI Selectors",
    "heading verification":                   "Verify Headings",
    "heading visibility":                     "Check Heading Visibility",
    "clickable selector coverage":            "Count Clickable Elements",
    "external link classification":           "Classify External Link",
    "clickable safety classification":        "Skip Protected Clickable",
    "sequential clickable interaction":       "Click Element",
    "sequential clickable interaction summary": "Clickable Summary",
    "javascript console health":              "Check Console Errors",
    "network resource health":               "Check Network Requests",
    "login page discovery":                  "Discover Login Controls",
    "login interaction":                     "Login Interaction",
    "login credential entry":                "Fill Login Credentials",
    "navigated page validation":             "Validate Navigated Page",
    "page automation failure":               "Page Automation",
}


def _action_label(scenario: str) -> str:
    return _ACTION_MAP.get(scenario.strip().lower(), scenario.title())


def _extract_element(steps: str) -> str:
    """Return a short element label from the steps string, or ''."""
    if not steps:
        return ""
    patterns = [
        r"(?:Locate (?:button|dropdown|field|checkbox|radio button|heading):\s*)([^\n]+)",
        r"(?:button:\s*)([^\n]+)",
        r"(?:dropdown:\s*)([^\n]+)",
        r"(?:field:\s*)([^\n]+)",
        r"(?:checkbox:\s*)([^\n]+)",
        r"(?:Link:\s*)(https?://[^\n]{0,80})",
        r"(?:Text:\s*)([^\n]+)",
    ]
    for pat in patterns:
        m = re.search(pat, steps, re.I)
        if m:
            label = m.group(1).strip()
            return label[:55] if label else ""
    return ""


def _short_error(actual: str) -> str:
    """Strip verbose prefixes and return a concise failure reason."""
    prefixes = (
        "Click failed: ",
        "Interaction failed: ",
        "Heading verification failed: ",
        "Request failed: ",
        "Automation failed: ",
        "Login test failed: ",
        "Form interaction failed: ",
    )
    txt = (actual or "").split("\n")[0]
    for p in prefixes:
        if txt.startswith(p):
            txt = txt[len(p):]
            break
    return txt[:90]


class StepLogger:
    """Prints numbered, coloured step lines and a final summary."""

    def __init__(self) -> None:
        self._step = 0
        self._passed = 0
        self._failed = 0
        self._color = sys.stdout.isatty()

    # ── internal helpers ────────────────────────────────────────────────────

    def _c(self, code: str, text: str) -> str:
        return f"{code}{text}{_RESET}" if self._color else text

    def reset(self) -> None:
        self._step = 0
        self._passed = 0
        self._failed = 0

    # ── public API ──────────────────────────────────────────────────────────

    def start(self, url: str, page_count: int) -> None:
        bar = "═" * 68
        print(f"\n{self._c(_BOLD, bar)}")
        print(f"{self._c(_BOLD, '  🌐  WebScanner — Functional Test Execution')}")
        print(f"{self._c(_BOLD, f'  Target  : {url}')}")
        print(f"{self._c(_BOLD, f'  Pages   : {page_count} page(s) queued')}")
        print(f"{self._c(_BOLD, bar)}")

    def section(self, title: str) -> None:
        bar = self._c(_CYAN + _BOLD, "─" * 70)
        print(f"\n{bar}")
        print(f"{self._c(_CYAN + _BOLD, f'  {title}')}")
        print(bar)

    def log(self, scenario: str, steps: str, actual: str, passed: bool) -> None:
        self._step += 1
        n = self._step

        action  = _action_label(scenario)
        element = _extract_element(steps)
        elem_tag = f' "{element}"' if element else ""

        if passed:
            self._passed += 1
            status = self._c(_GREEN + _BOLD, "SUCCESS")
        else:
            self._failed += 1
            err = _short_error(actual)
            reason = f" ({err})" if err else ""
            status = self._c(_RED + _BOLD, f"FAILED{reason}")

        # ── main step line ──────────────────────────────────────────────────
        step_lbl = self._c(_BOLD, f"[STEP {n:>3}]")
        arrow    = self._c(_DIM, "→")
        # pad action+element together to keep arrow aligned
        body = f"{action}{elem_tag}"
        print(f"{step_lbl} {body:<55} {arrow} {status}")

        # ── element-level detail line ───────────────────────────────────────
        if element:
            detail = self._detail(scenario, element, passed, _short_error(actual) if not passed else "")
            indent = "           " + self._c(_DIM, "↳") + " "
            colour = _RESET if passed else _RED
            print(f"{indent}{self._c(colour, detail)}")

    def screenshot_saved(self, path: str) -> None:
        indent = "           "
        print(f"{indent}{self._c(_YELLOW, '📸 Screenshot saved:')} {path}")

    def skip(self, action: str, element: str, reason: str = "already tested") -> None:
        """Log a skipped element without counting it as pass or fail."""
        self._step += 1
        n = self._step
        step_lbl = self._c(_BOLD, f"[STEP {n:>3}]")
        arrow    = self._c(_DIM, "→")
        body     = f"{action} \"{element}\"" if element else action
        status   = self._c(_YELLOW, "SKIPPED")
        print(f"{step_lbl} {body:<55} {arrow} {status}")
        print(f"           {self._c(_DIM, '↳')} {self._c(_DIM, f'{element!r} {reason} – SKIPPED')}")

    def summary(self) -> None:
        total = self._step
        bar = "═" * 54
        rate = (self._passed / total * 100) if total else 0.0
        print(f"\n{self._c(_BOLD, bar)}")
        print(f"{self._c(_BOLD, '  FINAL EXECUTION SUMMARY')}")
        print(f"{self._c(_BOLD, bar)}")
        print(f"  Total Steps  : {self._c(_BOLD, str(total))}")
        print(f"  Passed       : {self._c(_GREEN + _BOLD, str(self._passed))}")
        print(f"  Failed       : {self._c(_RED + _BOLD, str(self._failed))}")
        print(f"  Pass Rate    : {self._c(_BOLD, f'{rate:.1f}%')}")
        print(f"{self._c(_BOLD, bar)}\n")

    # ── detail message builder ──────────────────────────────────────────────

    def _detail(self, scenario: str, element: str, passed: bool, error: str) -> str:
        s = scenario.lower()
        if passed:
            if "button" in s:
                return f'"{element}" Button working fine'
            if "dropdown" in s:
                return f'Dropdown "{element}" opened successfully'
            if "checkbox" in s:
                return f'Checkbox "{element}" clicked successfully'
            if "radio" in s:
                return f'Radio button "{element}" selected successfully'
            if "input" in s or "field" in s:
                return f'Input field "{element}" filled successfully'
            if "link" in s:
                return f'Link "{element}" is reachable'
            if "form" in s:
                return f'Form submitted successfully'
            if "login" in s:
                return f'"{element}" Login module opened successfully'
            if "heading" in s:
                return f'Heading "{element}" is visible'
            return f'"{element}" working fine'
        else:
            suffix = f": {error}" if error else ""
            if "button" in s:
                return f'Button "{element}" click failed{suffix}'
            if "dropdown" in s:
                return f'Dropdown "{element}" not opening or not selectable{suffix}'
            if "checkbox" in s:
                return f'Checkbox "{element}" not clickable{suffix}'
            if "radio" in s:
                return f'Radio button "{element}" not clickable{suffix}'
            if "input" in s or "field" in s:
                return f'Input field "{element}" not accepting input{suffix}'
            if "link" in s:
                return f'Link "{element}" broken or unreachable{suffix}'
            if "form" in s:
                return f'Form not submitting{suffix}'
            return f'"{element}" failed{suffix}'
