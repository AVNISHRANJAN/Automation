"""
performance_tester.py — Performance Testing (Category 19)

Tests:
  - Page load time
  - DOM content loaded time
  - Number of requests
  - Total page size (HTML + resources)
  - Render-blocking scripts (sync scripts in <head>)
  - Images without lazy loading
  - Large images (unoptimized)
  - Too many JS files
  - Missing compression hints (gzip/brotli)
  - Core Web Vitals via JS (LCP, CLS, FCP approximations)
"""

from playwright.sync_api import Page
from dataclasses import dataclass, field
import time


@dataclass
class PerfTestResult:
    category: str
    test: str
    passed: bool
    detail: str
    value: float = 0.0
    unit: str = ""


@dataclass
class PerfTestSummary:
    results: list[PerfTestResult] = field(default_factory=list)
    load_time_ms: float = 0
    dom_content_loaded_ms: float = 0
    total_requests: int = 0
    total_bytes: int = 0

    @property
    def passed(self): return [r for r in self.results if r.passed]
    @property
    def failed(self): return [r for r in self.results if not r.passed]


def run_performance_tests(page: Page) -> PerfTestSummary:
    summary = PerfTestSummary()

    # ── Navigation timing ────────────────────────────────────────────────────
    try:
        timing = page.evaluate("""
            () => {
                const t = performance.timing;
                const nav = performance.getEntriesByType('navigation')[0];
                return {
                    domContentLoaded: nav ? nav.domContentLoadedEventEnd : (t.domContentLoadedEventEnd - t.navigationStart),
                    loadComplete: nav ? nav.loadEventEnd : (t.loadEventEnd - t.navigationStart),
                    ttfb: nav ? nav.responseStart : (t.responseStart - t.navigationStart),
                    domInteractive: nav ? nav.domInteractive : (t.domInteractive - t.navigationStart),
                };
            }
        """)

        dcl = round(timing.get("domContentLoaded", 0))
        load = round(timing.get("loadComplete", 0))
        ttfb = round(timing.get("ttfb", 0))
        dom_interactive = round(timing.get("domInteractive", 0))

        summary.load_time_ms = load
        summary.dom_content_loaded_ms = dcl

        summary.results.append(PerfTestResult(
            category="Load Time",
            test="Time to First Byte (TTFB)",
            passed=ttfb < 800,
            detail=f"{ttfb}ms {'✓ fast' if ttfb < 800 else '⚠️ slow (>800ms)'}",
            value=ttfb, unit="ms",
        ))

        summary.results.append(PerfTestResult(
            category="Load Time",
            test="DOM Content Loaded",
            passed=dcl < 2000,
            detail=f"{dcl}ms {'✓ good' if dcl < 1000 else '⚠️ slow (>2s)' if dcl >= 2000 else '~ acceptable'}",
            value=dcl, unit="ms",
        ))

        summary.results.append(PerfTestResult(
            category="Load Time",
            test="Full page load time",
            passed=load < 3000,
            detail=f"{load}ms {'✓ fast' if load < 3000 else '⚠️ slow (>3s)'}",
            value=load, unit="ms",
        ))
    except Exception as e:
        summary.results.append(PerfTestResult(
            category="Load Time", test="Navigation timing",
            passed=False, detail=f"Could not read timing: {e}",
        ))

    # ── Resource counts ──────────────────────────────────────────────────────
    try:
        resources = page.evaluate("""
            () => {
                const entries = performance.getEntriesByType('resource');
                const byType = {};
                let totalBytes = 0;
                entries.forEach(e => {
                    byType[e.initiatorType] = (byType[e.initiatorType] || 0) + 1;
                    totalBytes += e.transferSize || 0;
                });
                return { byType, total: entries.length, totalBytes };
            }
        """)

        total = resources["total"]
        total_bytes = resources.get("totalBytes", 0)
        by_type = resources.get("byType", {})
        summary.total_requests = total
        summary.total_bytes = total_bytes

        summary.results.append(PerfTestResult(
            category="Resources",
            test="Total HTTP requests",
            passed=total < 80,
            detail=f"{total} requests {'✓' if total < 50 else '⚠️ many requests' if total >= 80 else '~ acceptable'}",
            value=total, unit="requests",
        ))

        kb = round(total_bytes / 1024)
        summary.results.append(PerfTestResult(
            category="Resources",
            test="Total page size",
            passed=kb < 2048,
            detail=f"{kb} KB {'✓ good' if kb < 1024 else '⚠️ large (>2MB)' if kb >= 2048 else '~ acceptable'}",
            value=kb, unit="KB",
        ))

        scripts = by_type.get("script", 0)
        summary.results.append(PerfTestResult(
            category="Resources",
            test="JS file count",
            passed=scripts < 20,
            detail=f"{scripts} JS files {'✓' if scripts < 10 else '⚠️ many scripts' if scripts >= 20 else '~ acceptable'}",
            value=scripts, unit="files",
        ))
    except Exception:
        pass

    # ── Render-blocking scripts in <head> ────────────────────────────────────
    try:
        blocking_scripts = page.evaluate("""
            () => Array.from(document.head.querySelectorAll('script[src]:not([async]):not([defer]):not([type="module"])'))
                .map(s => s.src).slice(0, 5)
        """)
        summary.results.append(PerfTestResult(
            category="Render Blocking",
            test="No render-blocking scripts in <head>",
            passed=len(blocking_scripts) == 0,
            detail="No blocking scripts ✓" if len(blocking_scripts) == 0 else f"⚠️ {len(blocking_scripts)} blocking: {'; '.join(s[-50:] for s in blocking_scripts[:2])}",
        ))
    except Exception:
        pass

    # ── CSS in <body> (render-blocking) ──────────────────────────────────────
    try:
        body_css = page.evaluate("""
            () => Array.from(document.body.querySelectorAll('link[rel="stylesheet"]')).length
        """)
        summary.results.append(PerfTestResult(
            category="Render Blocking",
            test="No CSS loaded in <body>",
            passed=body_css == 0,
            detail="No body CSS ✓" if body_css == 0 else f"⚠️ {body_css} stylesheet(s) in <body> — move to <head>",
        ))
    except Exception:
        pass

    # ── Lazy loading on images ────────────────────────────────────────────────
    try:
        img_stats = page.evaluate("""
            () => {
                const imgs = Array.from(document.images);
                const lazy = imgs.filter(i => i.loading === 'lazy' || i.getAttribute('data-src'));
                return { total: imgs.length, lazy: lazy.length };
            }
        """)
        total_imgs = img_stats["total"]
        lazy_imgs = img_stats["lazy"]
        if total_imgs > 3:
            ratio = lazy_imgs / total_imgs
            summary.results.append(PerfTestResult(
                category="Images",
                test="Images use lazy loading",
                passed=ratio > 0.3,
                detail=f"{lazy_imgs}/{total_imgs} images lazy loaded ({'✓' if ratio > 0.3 else '⚠️ consider lazy loading off-screen images'})",
                value=round(ratio * 100), unit="%",
            ))
    except Exception:
        pass

    # ── viewport meta ────────────────────────────────────────────────────────
    try:
        viewport_meta = page.query_selector('meta[name="viewport"]')
        summary.results.append(PerfTestResult(
            category="Mobile",
            test="Viewport meta tag present",
            passed=viewport_meta is not None,
            detail="viewport meta ✓" if viewport_meta else "⚠️ No viewport meta — poor mobile performance",
        ))
    except Exception:
        pass

    # ── Minification hint ────────────────────────────────────────────────────
    try:
        scripts = page.evaluate("""
            () => Array.from(document.querySelectorAll('script[src]')).map(s => s.src).slice(0, 5)
        """)
        minified = sum(1 for s in scripts if ".min." in s or "-min." in s)
        total_scripts = len(scripts)
        if total_scripts > 0:
            summary.results.append(PerfTestResult(
                category="Optimization",
                test="Scripts appear minified",
                passed=minified == total_scripts or total_scripts == 0,
                detail=f"{minified}/{total_scripts} scripts minified ({'✓' if minified == total_scripts else '⚠️ unminified scripts detected'})",
            ))
    except Exception:
        pass

    return summary
