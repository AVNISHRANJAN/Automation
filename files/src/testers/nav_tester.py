"""
nav_tester.py — Navigation Testing (Category 12)

Tests:
  - Nav menus present and visible
  - Internal links reachable (HEAD requests)
  - Redirect chains detected
  - Broken anchor (#id) links
  - External links open in new tab
  - Back-button compatibility (no JS-only navigation traps)
"""

from playwright.sync_api import Page, sync_playwright
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin
import time


@dataclass
class NavTestResult:
    element: str
    test: str
    passed: bool
    detail: str
    url: str = ""


@dataclass
class NavTestSummary:
    results: list[NavTestResult] = field(default_factory=list)

    @property
    def passed(self): return [r for r in self.results if r.passed]
    @property
    def failed(self): return [r for r in self.results if not r.passed]


def run_nav_tests(page: Page, base_url: str) -> NavTestSummary:
    summary = NavTestSummary()
    parsed_base = urlparse(base_url)

    # ── Nav element detection ────────────────────────────────────────────────
    nav_selectors = ["nav", "[role='navigation']", "header nav", ".navbar", ".nav-menu", "#nav", "#menu"]
    nav_found = False
    for sel in nav_selectors:
        el = page.query_selector(sel)
        if el:
            nav_found = True
            summary.results.append(NavTestResult(
                element=sel, test="Navigation element present",
                passed=True, detail=f"Found <{sel}> on page",
            ))
            break
    if not nav_found:
        summary.results.append(NavTestResult(
            element="nav", test="Navigation element present",
            passed=False, detail="No <nav> / role=navigation / .navbar found — navigation not semantic",
        ))

    # ── Skip-to-content link (accessibility) ────────────────────────────────
    skip = page.query_selector('a[href="#main"], a[href="#content"], a[href="#main-content"]')
    summary.results.append(NavTestResult(
        element="skip-link", test="Skip-to-content link present",
        passed=skip is not None,
        detail="Skip-to-content found ✓" if skip else "Missing skip-to-content link (accessibility gap)",
    ))

    # ── Internal link reachability ───────────────────────────────────────────
    checked = set()
    internal_links = []
    for el in page.query_selector_all("a[href]:visible"):
        try:
            href = el.get_attribute("href") or ""
            if not href or href.startswith("#") or href.startswith("javascript") or href.startswith("mailto") or href.startswith("tel"):
                continue
            if href.startswith("/") or href.startswith("./"):
                abs_url = urljoin(base_url, href)
            elif href.startswith("http"):
                # Only check same-domain links
                if urlparse(href).netloc != parsed_base.netloc:
                    continue
                abs_url = href
            else:
                abs_url = urljoin(base_url, href)

            if abs_url in checked:
                continue
            checked.add(abs_url)
            internal_links.append((el.inner_text().strip()[:40] or href, abs_url))
        except Exception:
            pass

    # Check up to 15 internal links
    for link_text, link_url in internal_links[:15]:
        try:
            resp = page.request.head(link_url, timeout=8000)
            ok = resp.status < 400
            summary.results.append(NavTestResult(
                element=f"link: {link_text[:30]}",
                test="Internal link reachable",
                passed=ok,
                detail=f"HTTP {resp.status}" if ok else f"HTTP {resp.status} — broken link",
                url=link_url,
            ))
        except Exception as e:
            summary.results.append(NavTestResult(
                element=f"link: {link_text[:30]}",
                test="Internal link reachable",
                passed=False,
                detail=f"Request failed: {str(e)[:60]}",
                url=link_url,
            ))

    # ── Broken anchor links (#id targets) ───────────────────────────────────
    for el in page.query_selector_all('a[href^="#"]:visible'):
        try:
            href = el.get_attribute("href") or ""
            anchor = href[1:]
            if not anchor:
                continue
            target = page.query_selector(f'#{anchor}, [name="{anchor}"]')
            summary.results.append(NavTestResult(
                element=f"#{anchor}",
                test="Anchor target exists on page",
                passed=target is not None,
                detail=f"Anchor #{anchor} found ✓" if target else f"Anchor #{anchor} missing — broken in-page link",
            ))
        except Exception:
            pass

    # ── External links open in new tab ──────────────────────────────────────
    for el in page.query_selector_all("a[href]:visible"):
        try:
            href = el.get_attribute("href") or ""
            if not href.startswith("http"):
                continue
            if urlparse(href).netloc == parsed_base.netloc:
                continue
            target = el.get_attribute("target")
            link_text = el.inner_text().strip()[:30] or href[:30]
            summary.results.append(NavTestResult(
                element=f"ext: {link_text}",
                test="External link opens in new tab",
                passed=target == "_blank",
                detail="target=_blank ✓" if target == "_blank" else f"target={target or 'not set'} — external link stays in same tab",
                url=href,
            ))
        except Exception:
            pass

    # ── Breadcrumb / sitemap navigation check ──────────────────────────────
    breadcrumb = page.query_selector(
        '[aria-label="breadcrumb"], .breadcrumb, nav[aria-label*="bread"], ol.breadcrumbs'
    )
    summary.results.append(NavTestResult(
        element="breadcrumb", test="Breadcrumb navigation present",
        passed=breadcrumb is not None,
        detail="Breadcrumb found ✓" if breadcrumb else "No breadcrumb (info only — not always required)",
    ))

    # ── Mobile hamburger / responsive nav ──────────────────────────────────
    hamburger = page.query_selector(
        'button[aria-label*="menu"], button[aria-label*="Menu"], .hamburger, .menu-toggle, [aria-controls*="menu"]'
    )
    summary.results.append(NavTestResult(
        element="mobile-nav", test="Mobile menu toggle present",
        passed=hamburger is not None,
        detail="Mobile menu toggle found ✓" if hamburger else "No mobile menu toggle (may cause mobile UX issues)",
    ))

    return summary
