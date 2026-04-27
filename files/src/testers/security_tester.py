"""
security_tester.py — Security Testing (Category 20)

Tests:
  - Security HTTP headers (CSP, HSTS, X-Frame-Options, etc.)
  - Mixed content (HTTP resources on HTTPS page)
  - XSS sink detection in DOM (innerHTML usage hints)
  - SQL injection surface area (numeric inputs without validation)
  - Exposed sensitive info in HTML (API keys, tokens, internal paths)
  - Clickjacking protection
  - Open redirect indicators
  - Autocomplete on sensitive fields
"""

from playwright.sync_api import Page
from dataclasses import dataclass, field
import re


@dataclass
class SecurityTestResult:
    category: str
    test: str
    passed: bool
    detail: str
    severity: str = "medium"  # low / medium / high / critical


@dataclass
class SecurityTestSummary:
    results: list[SecurityTestResult] = field(default_factory=list)

    @property
    def passed(self): return [r for r in self.results if r.passed]
    @property
    def failed(self): return [r for r in self.results if not r.passed]
    @property
    def critical(self): return [r for r in self.results if not r.passed and r.severity == "critical"]
    @property
    def high(self): return [r for r in self.results if not r.passed and r.severity == "high"]


SECURITY_HEADERS = {
    "Content-Security-Policy":          ("critical", "Prevents XSS and injection attacks"),
    "Strict-Transport-Security":        ("high",     "Forces HTTPS — prevents downgrade attacks"),
    "X-Frame-Options":                  ("high",     "Prevents clickjacking"),
    "X-Content-Type-Options":           ("medium",   "Prevents MIME sniffing"),
    "Referrer-Policy":                  ("medium",   "Controls referrer leakage"),
    "Permissions-Policy":               ("low",      "Limits browser API access"),
    "X-XSS-Protection":                 ("low",      "Legacy XSS filter (supplementary)"),
    "Cross-Origin-Opener-Policy":       ("medium",   "Prevents cross-origin attacks"),
    "Cross-Origin-Resource-Policy":     ("low",      "Controls resource sharing"),
}

# Patterns that suggest exposed secrets
SECRET_PATTERNS = [
    (r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?([a-z0-9\-_]{20,})', "API Key exposure"),
    (r'(?i)(secret[_-]?key|secretkey)\s*[=:]\s*["\']?([a-z0-9\-_]{20,})', "Secret key exposure"),
    (r'(?i)aws[_-]?access[_-]?key[_-]?id\s*[=:]\s*["\']?([A-Z0-9]{20})', "AWS Access Key exposure"),
    (r'(?i)password\s*[=:]\s*["\']([^"\']{4,})["\']', "Hardcoded password"),
    (r'(?i)private[_-]?key\s*[=:]\s*["\']?([a-z0-9\-_]{20,})', "Private key exposure"),
    (r'-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----', "Private key in page"),
    (r'(?i)authorization\s*:\s*bearer\s+([a-z0-9\-_.~+/=]{20,})', "Bearer token exposed"),
]


def run_security_tests(page: Page, url: str) -> SecurityTestSummary:
    summary = SecurityTestSummary()

    # ── HTTP Security Headers ────────────────────────────────────────────────
    try:
        resp = page.request.get(url, timeout=10000)
        headers = {k.lower(): v for k, v in resp.headers.items()}

        for header, (severity, description) in SECURITY_HEADERS.items():
            present = header.lower() in headers
            value = headers.get(header.lower(), "")
            summary.results.append(SecurityTestResult(
                category="HTTP Headers",
                test=f"Header: {header}",
                passed=present,
                severity=severity,
                detail=f"{header}: {value[:80]} ✓" if present else f"⚠️ Missing {header} — {description}",
            ))

        # HSTS max-age check
        hsts = headers.get("strict-transport-security", "")
        if hsts:
            max_age_match = re.search(r"max-age=(\d+)", hsts)
            if max_age_match:
                max_age = int(max_age_match.group(1))
                summary.results.append(SecurityTestResult(
                    category="HTTP Headers",
                    test="HSTS max-age ≥ 1 year",
                    passed=max_age >= 31536000,
                    severity="high",
                    detail=f"max-age={max_age} ✓" if max_age >= 31536000 else f"⚠️ max-age={max_age} — should be ≥31536000 (1 year)",
                ))

        # CSP frame-ancestors vs X-Frame-Options
        csp = headers.get("content-security-policy", "")
        xfo = headers.get("x-frame-options", "")
        has_clickjack_protection = bool(csp and "frame-ancestors" in csp) or bool(xfo)
        summary.results.append(SecurityTestResult(
            category="Clickjacking",
            test="Clickjacking protection present",
            passed=has_clickjack_protection,
            severity="high",
            detail="frame-ancestors/X-Frame-Options ✓" if has_clickjack_protection else "⚠️ No clickjacking protection",
        ))

    except Exception as e:
        summary.results.append(SecurityTestResult(
            category="HTTP Headers", test="Header analysis",
            passed=False, severity="medium",
            detail=f"Could not fetch headers: {str(e)[:60]}",
        ))

    # ── Mixed content ─────────────────────────────────────────────────────────
    if page.url.startswith("https://"):
        try:
            mixed = page.evaluate("""
                () => {
                    const http = (src) => src && src.startsWith('http:');
                    return [
                        ...Array.from(document.images).filter(i => http(i.src)).map(i => 'img: ' + i.src),
                        ...Array.from(document.querySelectorAll('script[src]')).filter(s => http(s.src)).map(s => 'script: ' + s.src),
                        ...Array.from(document.querySelectorAll('link[href]')).filter(l => http(l.href)).map(l => 'css: ' + l.href),
                    ].slice(0, 5);
                }
            """)
            summary.results.append(SecurityTestResult(
                category="Mixed Content",
                test="No HTTP resources on HTTPS page",
                passed=len(mixed) == 0,
                severity="high",
                detail="No mixed content ✓" if len(mixed) == 0 else f"⚠️ {len(mixed)} HTTP resource(s): {'; '.join(m[:50] for m in mixed[:2])}",
            ))
        except Exception:
            pass

    # ── Exposed secrets in source ────────────────────────────────────────────
    try:
        page_source = page.content()
        found_secrets = []
        for pattern, label in SECRET_PATTERNS:
            match = re.search(pattern, page_source)
            if match:
                found_secrets.append(label)

        summary.results.append(SecurityTestResult(
            category="Secrets",
            test="No secrets exposed in page source",
            passed=len(found_secrets) == 0,
            severity="critical",
            detail="No exposed secrets found ✓" if len(found_secrets) == 0 else f"🚨 CRITICAL — Exposed: {', '.join(found_secrets)}",
        ))
    except Exception:
        pass

    # ── XSS: innerHTML usage in inline scripts ────────────────────────────────
    try:
        xss_sinks = page.evaluate("""
            () => {
                const scripts = Array.from(document.querySelectorAll('script:not([src])')).map(s => s.textContent || '');
                const sinks = ['innerHTML', 'outerHTML', 'document.write', 'eval(', 'Function('];
                const found = [];
                scripts.forEach(src => {
                    sinks.forEach(sink => { if (src.includes(sink)) found.push(sink); });
                });
                return [...new Set(found)];
            }
        """)
        summary.results.append(SecurityTestResult(
            category="XSS",
            test="No dangerous DOM sinks in inline JS",
            passed=len(xss_sinks) == 0,
            severity="high",
            detail="No innerHTML/eval sinks in inline scripts ✓" if len(xss_sinks) == 0 else f"⚠️ Dangerous sinks found: {', '.join(xss_sinks)} — verify inputs are sanitized",
        ))
    except Exception:
        pass

    # ── SQL injection surface: unvalidated number/text inputs ────────────────
    try:
        unvalidated_inputs = page.evaluate("""
            () => Array.from(document.querySelectorAll('input[type="text"]:not([pattern]):not([maxlength])'))
                .map(i => i.name || i.id || 'unknown').slice(0, 5)
        """)
        summary.results.append(SecurityTestResult(
            category="SQL Injection",
            test="Text inputs have validation constraints",
            passed=len(unvalidated_inputs) == 0,
            severity="medium",
            detail="All text inputs have constraints ✓" if len(unvalidated_inputs) == 0 else f"⚠️ {len(unvalidated_inputs)} unconstrained input(s): {', '.join(unvalidated_inputs[:3])} — validate server-side",
        ))
    except Exception:
        pass

    # ── Autocomplete on sensitive fields ─────────────────────────────────────
    try:
        pw_ac_off = page.evaluate("""
            () => Array.from(document.querySelectorAll('input[type="password"]'))
                .filter(i => !['off','current-password','new-password'].includes(i.autocomplete))
                .length
        """)
        summary.results.append(SecurityTestResult(
            category="Autocomplete",
            test="Password fields have secure autocomplete",
            passed=pw_ac_off == 0,
            severity="medium",
            detail="Password autocomplete configured ✓" if pw_ac_off == 0 else f"⚠️ {pw_ac_off} password field(s) with missing autocomplete attribute",
        ))
    except Exception:
        pass

    # ── Open redirect indicators ──────────────────────────────────────────────
    try:
        links = page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
                .map(a => a.href)
                .filter(h => /[?&](url|redirect|next|return|goto|dest)=http/i.test(h))
                .slice(0, 3)
        """)
        summary.results.append(SecurityTestResult(
            category="Open Redirect",
            test="No open redirect parameters in links",
            passed=len(links) == 0,
            severity="high",
            detail="No open redirect params found ✓" if len(links) == 0 else f"⚠️ Possible open redirects: {'; '.join(l[:60] for l in links)}",
        ))
    except Exception:
        pass

    # ── Subresource Integrity on CDN scripts ─────────────────────────────────
    try:
        sri_stats = page.evaluate("""
            () => {
                const cdnScripts = Array.from(document.querySelectorAll('script[src]'))
                    .filter(s => !s.src.includes(location.hostname));
                const withSRI = cdnScripts.filter(s => s.integrity);
                return { total: cdnScripts.length, withSRI: withSRI.length };
            }
        """)
        total_cdn = sri_stats["total"]
        with_sri = sri_stats["withSRI"]
        if total_cdn > 0:
            summary.results.append(SecurityTestResult(
                category="SRI",
                test="CDN scripts have integrity (SRI) hashes",
                passed=with_sri == total_cdn,
                severity="medium",
                detail=f"{with_sri}/{total_cdn} CDN scripts use SRI ✓" if with_sri == total_cdn else f"⚠️ {total_cdn - with_sri} CDN script(s) missing SRI integrity attribute",
            ))
    except Exception:
        pass

    return summary
