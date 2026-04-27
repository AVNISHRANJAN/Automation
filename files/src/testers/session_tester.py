"""
session_tester.py — Session Testing (Category 14)

Tests:
  - Session cookie attributes (HttpOnly, Secure, SameSite)
  - Cookie expiry / session vs persistent
  - Multiple session cookie detection
  - localStorage / sessionStorage usage
  - Inactivity timeout scripts/meta hints
"""

from playwright.sync_api import Page
from dataclasses import dataclass, field
import json


@dataclass
class SessionTestResult:
    category: str
    test: str
    passed: bool
    detail: str


@dataclass
class SessionTestSummary:
    results: list[SessionTestResult] = field(default_factory=list)
    cookies: list[dict] = field(default_factory=list)

    @property
    def passed(self): return [r for r in self.results if r.passed]
    @property
    def failed(self): return [r for r in self.results if not r.passed]


SESSION_COOKIE_NAMES = [
    "session", "sess", "sid", "sessionid", "phpsessid", "jsessionid",
    "asp.net_sessionid", "connect.sid", "auth", "token", "authtoken",
    "access_token", "refresh_token", "remember_token",
]


def run_session_tests(page: Page) -> SessionTestSummary:
    summary = SessionTestSummary()

    # ── Collect cookies ──────────────────────────────────────────────────────
    try:
        all_cookies = page.context.cookies()
        summary.cookies = all_cookies

        session_cookies = [
            c for c in all_cookies
            if any(name in c["name"].lower() for name in SESSION_COOKIE_NAMES)
        ]

        summary.results.append(SessionTestResult(
            category="Cookies",
            test="Session cookies detected",
            passed=len(session_cookies) > 0,
            detail=f"Found {len(session_cookies)} session cookie(s): {', '.join(c['name'] for c in session_cookies[:5])}" if session_cookies else "No session cookies found (may not be logged in)",
        ))

        for cookie in session_cookies[:5]:
            name = cookie["name"]

            # HttpOnly
            http_only = cookie.get("httpOnly", False)
            summary.results.append(SessionTestResult(
                category="Cookie Security",
                test=f"HttpOnly: {name}",
                passed=http_only,
                detail=f"HttpOnly=True ✓" if http_only else f"⚠️ HttpOnly=False — cookie accessible via JS (XSS risk)",
            ))

            # Secure flag
            secure = cookie.get("secure", False)
            summary.results.append(SessionTestResult(
                category="Cookie Security",
                test=f"Secure flag: {name}",
                passed=secure,
                detail="Secure=True ✓" if secure else "⚠️ Secure=False — cookie sent over HTTP too",
            ))

            # SameSite
            samesite = cookie.get("sameSite", "").lower()
            good_samesite = samesite in ("strict", "lax")
            summary.results.append(SessionTestResult(
                category="Cookie Security",
                test=f"SameSite: {name}",
                passed=good_samesite,
                detail=f"SameSite={samesite} ✓" if good_samesite else f"⚠️ SameSite={samesite or 'not set'} — CSRF risk",
            ))

            # Session vs persistent
            expires = cookie.get("expires", -1)
            is_session = expires == -1 or expires == 0
            summary.results.append(SessionTestResult(
                category="Cookie Lifetime",
                test=f"Session cookie (no persistent expiry): {name}",
                passed=is_session,
                detail="Session cookie (cleared on browser close) ✓" if is_session else f"Persistent cookie — expires: {expires}",
            ))

    except Exception as e:
        summary.results.append(SessionTestResult(
            category="Cookies", test="Cookie access",
            passed=False, detail=f"Could not read cookies: {e}",
        ))

    # ── localStorage usage ───────────────────────────────────────────────────
    try:
        ls_keys = page.evaluate("() => Object.keys(localStorage)")
        has_sensitive = any(
            kw in key.lower() for key in ls_keys
            for kw in ["token", "auth", "session", "user", "password", "secret"]
        )
        summary.results.append(SessionTestResult(
            category="Storage",
            test="Sensitive data NOT in localStorage",
            passed=not has_sensitive,
            detail=f"No sensitive keys in localStorage ✓" if not has_sensitive else f"⚠️ Sensitive keys in localStorage: {[k for k in ls_keys if any(kw in k.lower() for kw in ['token','auth','session','user','password','secret'])][:5]}",
        ))
        summary.results.append(SessionTestResult(
            category="Storage",
            test="localStorage keys count",
            passed=True,
            detail=f"{len(ls_keys)} key(s): {ls_keys[:6]}",
        ))
    except Exception as e:
        summary.results.append(SessionTestResult(
            category="Storage", test="localStorage access",
            passed=False, detail=f"Could not read localStorage: {e}",
        ))

    # ── sessionStorage usage ─────────────────────────────────────────────────
    try:
        ss_keys = page.evaluate("() => Object.keys(sessionStorage)")
        has_sensitive_ss = any(
            kw in key.lower() for key in ss_keys
            for kw in ["password", "secret", "private_key"]
        )
        summary.results.append(SessionTestResult(
            category="Storage",
            test="No plaintext passwords in sessionStorage",
            passed=not has_sensitive_ss,
            detail=f"sessionStorage clean ✓ ({len(ss_keys)} keys)" if not has_sensitive_ss else "⚠️ Potentially sensitive data in sessionStorage",
        ))
    except Exception:
        pass

    # ── Inactivity timeout hints ─────────────────────────────────────────────
    try:
        page_text = page.inner_text("body").lower()
        timeout_hints = any(kw in page_text for kw in [
            "session expired", "timed out", "inactive", "inactivity",
            "auto logout", "automatic logout", "session timeout"
        ])
        # Check for timeout JS patterns
        timeout_js = page.evaluate("""
            () => {
                const scripts = Array.from(document.querySelectorAll('script')).map(s => s.textContent || '');
                return scripts.some(s => s.includes('setTimeout') && (s.includes('logout') || s.includes('session') || s.includes('expire')));
            }
        """)
        summary.results.append(SessionTestResult(
            category="Session Timeout",
            test="Session timeout / auto-logout implemented",
            passed=timeout_hints or timeout_js,
            detail="Timeout mechanism detected ✓" if (timeout_hints or timeout_js) else "No session timeout detected (may be server-side only)",
        ))
    except Exception:
        pass

    return summary
