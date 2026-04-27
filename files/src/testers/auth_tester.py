"""
auth_tester.py — Authentication Testing (Category 13)

Tests:
  - Login form present & secure
  - Signup form detection
  - Logout button/link present
  - Password reset / forgot password flow
  - HTTPS enforcement
  - CSRF token presence
  - Autocomplete off on sensitive fields
  - Login rate-limit hint detection
"""

from playwright.sync_api import Page
from dataclasses import dataclass, field


@dataclass
class AuthTestResult:
    category: str
    test: str
    passed: bool
    detail: str


@dataclass
class AuthTestSummary:
    results: list[AuthTestResult] = field(default_factory=list)
    has_login_form: bool = False
    has_signup_form: bool = False
    has_logout: bool = False
    has_password_reset: bool = False

    @property
    def passed(self): return [r for r in self.results if r.passed]
    @property
    def failed(self): return [r for r in self.results if not r.passed]


def run_auth_tests(page: Page, url: str) -> AuthTestSummary:
    summary = AuthTestSummary()
    page_text = page.inner_text("body").lower()

    # ── HTTPS check ──────────────────────────────────────────────────────────
    is_https = page.url.startswith("https://")
    summary.results.append(AuthTestResult(
        category="Security",
        test="Page served over HTTPS",
        passed=is_https,
        detail="HTTPS ✓ — connection is encrypted" if is_https else "⚠️ HTTP — credentials may be sent in plaintext!",
    ))

    # ── Login form detection ─────────────────────────────────────────────────
    password_inputs = page.query_selector_all('input[type="password"]:visible')
    has_password = len(password_inputs) > 0
    email_or_user = page.query_selector(
        'input[type="email"]:visible, input[name*="user"]:visible, input[name*="login"]:visible, input[placeholder*="email" i]:visible, input[placeholder*="username" i]:visible'
    )

    if has_password and email_or_user:
        summary.has_login_form = True
        summary.results.append(AuthTestResult(
            category="Login", test="Login form detected",
            passed=True, detail="Found email/username + password fields",
        ))

        # CSRF token
        csrf = page.query_selector(
            'input[name*="csrf"], input[name*="_token"], input[name*="authenticity"], input[type="hidden"][name*="token"]'
        )
        summary.results.append(AuthTestResult(
            category="Login", test="CSRF token in login form",
            passed=csrf is not None,
            detail="CSRF token found ✓" if csrf else "⚠️ No CSRF token detected — potential CSRF vulnerability",
        ))

        # Autocomplete on password
        for pw in password_inputs:
            ac = pw.get_attribute("autocomplete")
            name = pw.get_attribute("name") or "password"
            is_ok = ac in ("current-password", "new-password", "off")
            summary.results.append(AuthTestResult(
                category="Login", test=f"Password autocomplete ({name})",
                passed=is_ok,
                detail=f"autocomplete={ac} ✓" if is_ok else f"autocomplete={ac or 'not set'} — should be current-password",
            ))

        # Forgot password link
        forgot = page.query_selector(
            'a[href*="forgot"], a[href*="reset"], a:text-matches("forgot.*(password)?", "i"), a:text-matches("reset.*(password)?", "i")'
        )
        if not forgot:
            # fallback: text scan
            forgot_text = any(kw in page_text for kw in ["forgot password", "reset password", "forgot your password"])
            summary.has_password_reset = forgot_text
            summary.results.append(AuthTestResult(
                category="Login", test="Forgot/Reset password link",
                passed=forgot_text,
                detail="Password reset link found ✓" if forgot_text else "No forgot password link detected",
            ))
        else:
            summary.has_password_reset = True
            summary.results.append(AuthTestResult(
                category="Login", test="Forgot/Reset password link",
                passed=True, detail=f"Link found: {forgot.get_attribute('href') or forgot.inner_text()[:30]}",
            ))

        # Rate limit / CAPTCHA hint
        has_captcha = page.query_selector('[class*="captcha" i], [id*="captcha" i], .g-recaptcha, iframe[src*="recaptcha"]') is not None
        has_rate_hint = any(kw in page_text for kw in ["too many attempts", "locked", "rate limit", "try again later"])
        summary.results.append(AuthTestResult(
            category="Login", test="Brute-force protection (CAPTCHA/rate limit hint)",
            passed=has_captcha or has_rate_hint,
            detail="CAPTCHA or rate-limit messaging found ✓" if (has_captcha or has_rate_hint) else "No brute-force protection detected",
        ))

        # Remember me
        remember = page.query_selector(
            'input[type="checkbox"][name*="remember" i], input[type="checkbox"][id*="remember" i], label:text-matches("remember", "i")'
        )
        summary.results.append(AuthTestResult(
            category="Login", test="Remember me option",
            passed=remember is not None,
            detail="Remember me present ✓" if remember else "No remember me option (info only)",
        ))

    else:
        summary.results.append(AuthTestResult(
            category="Login", test="Login form detected",
            passed=False, detail="No login form found on this page",
        ))

    # ── Signup form detection ────────────────────────────────────────────────
    has_confirm_pw = len(password_inputs) >= 2
    signup_signals = any(kw in page_text for kw in ["sign up", "register", "create account", "create an account"])
    if has_confirm_pw or (signup_signals and has_password):
        summary.has_signup_form = True
        summary.results.append(AuthTestResult(
            category="Signup", test="Signup/Register form detected",
            passed=True, detail="Confirm password or signup keywords found",
        ))

        # Confirm password field
        summary.results.append(AuthTestResult(
            category="Signup", test="Password confirmation field",
            passed=has_confirm_pw,
            detail="Confirm password field present ✓" if has_confirm_pw else "Only one password field — no confirmation",
        ))

        # Terms & conditions checkbox
        terms = page.query_selector(
            'input[type="checkbox"][name*="terms" i], input[type="checkbox"][id*="terms" i], label:text-matches("terms|agree|accept", "i")'
        )
        summary.results.append(AuthTestResult(
            category="Signup", test="Terms & conditions checkbox",
            passed=terms is not None,
            detail="T&C checkbox found ✓" if terms else "No terms/conditions checkbox",
        ))
    else:
        summary.results.append(AuthTestResult(
            category="Signup", test="Signup/Register form detected",
            passed=False, detail="No signup form found on this page",
        ))

    # ── Logout detection ─────────────────────────────────────────────────────
    logout_el = page.query_selector(
        'a[href*="logout"], a[href*="signout"], a[href*="sign-out"], button:text-matches("(log out|logout|sign out)", "i")'
    )
    logout_text = any(kw in page_text for kw in ["log out", "logout", "sign out"])
    summary.has_logout = logout_el is not None or logout_text
    summary.results.append(AuthTestResult(
        category="Logout", test="Logout option present",
        passed=summary.has_logout,
        detail="Logout button/link found ✓" if summary.has_logout else "No logout found (may be on authenticated pages only)",
    ))

    # ── Social auth / OAuth ──────────────────────────────────────────────────
    social_providers = {
        "Google": ['button:text-matches("google", "i")', 'a[href*="google"]', '[class*="google-btn"]'],
        "GitHub": ['button:text-matches("github", "i")', 'a[href*="github"]'],
        "Facebook": ['button:text-matches("facebook", "i")', 'a[href*="facebook"]'],
        "Apple": ['button:text-matches("apple", "i")', 'a[href*="apple"]'],
    }
    found_providers = []
    for provider, selectors in social_providers.items():
        for sel in selectors:
            try:
                if page.query_selector(sel):
                    found_providers.append(provider)
                    break
            except Exception:
                pass

    summary.results.append(AuthTestResult(
        category="Social Auth", test="OAuth / Social login options",
        passed=len(found_providers) > 0,
        detail=f"Found: {', '.join(found_providers)}" if found_providers else "No social login detected",
    ))

    return summary
