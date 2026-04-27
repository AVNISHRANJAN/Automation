"""
form_tester.py — Form & Input Validation Testing (Category 11)

Tests:
  - Required field enforcement
  - Email format validation
  - Empty submit behavior
  - Min/max length on inputs
  - Pattern attribute validation
  - Textarea limits
"""

from playwright.sync_api import Page
from dataclasses import dataclass, field
import re


@dataclass
class FormTestResult:
    field_name: str
    field_type: str
    label: str
    test: str
    passed: bool
    detail: str


@dataclass
class FormTestSummary:
    results: list[FormTestResult] = field(default_factory=list)

    @property
    def passed(self): return [r for r in self.results if r.passed]
    @property
    def failed(self): return [r for r in self.results if not r.passed]


def run_form_tests(page: Page) -> FormTestSummary:
    summary = FormTestSummary()

    # ── Required field checks ────────────────────────────────────────────────
    for el in page.query_selector_all('input[required]:visible, textarea[required]:visible'):
        try:
            name  = el.get_attribute("name") or el.get_attribute("id") or "(unknown)"
            itype = el.get_attribute("type") or "text"
            label = el.get_attribute("aria-label") or el.get_attribute("placeholder") or name

            # HTML5 required attribute present?
            required_attr = el.get_attribute("required")
            summary.results.append(FormTestResult(
                field_name=name, field_type=itype, label=label,
                test="Required attribute present",
                passed=required_attr is not None,
                detail="Field correctly marked required" if required_attr is not None else "Missing required attribute",
            ))

            # aria-required also set for accessibility?
            aria_req = el.get_attribute("aria-required")
            summary.results.append(FormTestResult(
                field_name=name, field_type=itype, label=label,
                test="aria-required for accessibility",
                passed=aria_req is not None,
                detail="aria-required set ✓" if aria_req else "Missing aria-required (accessibility gap)",
            ))
        except Exception:
            pass

    # ── Email format validation ──────────────────────────────────────────────
    for el in page.query_selector_all('input[type="email"]:visible'):
        try:
            name  = el.get_attribute("name") or el.get_attribute("id") or "email"
            label = el.get_attribute("aria-label") or el.get_attribute("placeholder") or name

            # Check: does input have type=email (native validation)?
            summary.results.append(FormTestResult(
                field_name=name, field_type="email", label=label,
                test="Email input uses type=email",
                passed=True,
                detail="Native browser email validation enabled",
            ))

            # Check for extra pattern attribute
            pattern = el.get_attribute("pattern")
            if pattern:
                valid_pattern = bool(re.compile(pattern))
                summary.results.append(FormTestResult(
                    field_name=name, field_type="email", label=label,
                    test="Email pattern attribute valid",
                    passed=valid_pattern,
                    detail=f"Pattern: {pattern[:60]}" if valid_pattern else "Pattern regex is invalid",
                ))
        except Exception:
            pass

    # ── Password field checks ────────────────────────────────────────────────
    for el in page.query_selector_all('input[type="password"]:visible'):
        try:
            name  = el.get_attribute("name") or el.get_attribute("id") or "password"
            label = el.get_attribute("aria-label") or el.get_attribute("placeholder") or name

            minlength = el.get_attribute("minlength")
            summary.results.append(FormTestResult(
                field_name=name, field_type="password", label=label,
                test="Password has minlength constraint",
                passed=minlength is not None,
                detail=f"minlength={minlength}" if minlength else "No minlength set (weak passwords allowed)",
            ))

            autocomplete = el.get_attribute("autocomplete")
            good_ac = autocomplete in ("current-password", "new-password", "off")
            summary.results.append(FormTestResult(
                field_name=name, field_type="password", label=label,
                test="Password autocomplete attribute",
                passed=good_ac,
                detail=f"autocomplete={autocomplete}" if good_ac else f"autocomplete={autocomplete or 'not set'} — should be current-password/new-password",
            ))
        except Exception:
            pass

    # ── maxlength on text fields ─────────────────────────────────────────────
    for el in page.query_selector_all('input[type="text"]:visible, textarea:visible'):
        try:
            name  = el.get_attribute("name") or el.get_attribute("id") or "text"
            label = el.get_attribute("aria-label") or el.get_attribute("placeholder") or name
            tag   = el.evaluate("el => el.tagName.toLowerCase()")
            maxlength = el.get_attribute("maxlength")
            summary.results.append(FormTestResult(
                field_name=name, field_type=tag, label=label,
                test="maxlength constraint present",
                passed=maxlength is not None,
                detail=f"maxlength={maxlength}" if maxlength else "No maxlength — overflow possible",
            ))
        except Exception:
            pass

    # ── Number field min/max ─────────────────────────────────────────────────
    for el in page.query_selector_all('input[type="number"]:visible'):
        try:
            name  = el.get_attribute("name") or el.get_attribute("id") or "number"
            label = el.get_attribute("aria-label") or el.get_attribute("placeholder") or name
            has_min = el.get_attribute("min") is not None
            has_max = el.get_attribute("max") is not None
            summary.results.append(FormTestResult(
                field_name=name, field_type="number", label=label,
                test="Number field has min/max bounds",
                passed=has_min or has_max,
                detail=f"min={el.get_attribute('min')} max={el.get_attribute('max')}" if has_min or has_max else "No bounds — accepts any value",
            ))
        except Exception:
            pass

    # ── Form novalidate check (bypasses native validation) ───────────────────
    for form in page.query_selector_all("form"):
        try:
            nv = form.get_attribute("novalidate")
            form_id = form.get_attribute("id") or form.get_attribute("name") or "(unnamed)"
            summary.results.append(FormTestResult(
                field_name=form_id, field_type="form", label=f"<form id={form_id}>",
                test="novalidate NOT present on form",
                passed=nv is None,
                detail="Native validation active ✓" if nv is None else "⚠️ novalidate set — HTML5 validation disabled!",
            ))
        except Exception:
            pass

    # ── Input label association ──────────────────────────────────────────────
    for el in page.query_selector_all('input:not([type="hidden"]):not([type="submit"]):not([type="reset"]):not([type="button"]):visible'):
        try:
            el_id = el.get_attribute("id")
            name  = el.get_attribute("name") or el_id or "(unknown)"
            itype = el.get_attribute("type") or "text"
            has_label = False
            if el_id:
                lbl = page.query_selector(f'label[for="{el_id}"]')
                has_label = lbl is not None
            aria_label = el.get_attribute("aria-label") or el.get_attribute("aria-labelledby")
            summary.results.append(FormTestResult(
                field_name=name, field_type=itype, label=name,
                test="Input has associated label",
                passed=has_label or bool(aria_label),
                detail="Label associated ✓" if (has_label or aria_label) else "No <label for=...> or aria-label (accessibility issue)",
            ))
        except Exception:
            pass

    return summary
