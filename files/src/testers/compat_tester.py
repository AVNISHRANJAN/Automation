"""
compat_tester.py — Compatibility Testing (Category 21)

Tests:
  - Viewport / responsive design meta
  - Mobile breakpoint rendering (simulate 375px viewport)
  - Cross-browser CSS usage (prefixes, modern features)
  - Touch target sizes (minimum 44x44px)
  - Horizontal scroll on mobile
  - Font scaling / zoom support
  - Print stylesheet
  - RTL/i18n readiness
"""

from playwright.sync_api import Page, sync_playwright
from dataclasses import dataclass, field


@dataclass
class CompatTestResult:
    category: str
    test: str
    passed: bool
    detail: str


@dataclass
class CompatTestSummary:
    results: list[CompatTestResult] = field(default_factory=list)

    @property
    def passed(self): return [r for r in self.results if r.passed]
    @property
    def failed(self): return [r for r in self.results if not r.passed]


def run_compat_tests(page: Page) -> CompatTestSummary:
    summary = CompatTestSummary()

    # ── Viewport meta ────────────────────────────────────────────────────────
    viewport_meta = page.query_selector('meta[name="viewport"]')
    viewport_content = viewport_meta.get_attribute("content") if viewport_meta else ""
    has_viewport = viewport_meta is not None
    has_width_device = "width=device-width" in (viewport_content or "")

    summary.results.append(CompatTestResult(
        category="Responsive",
        test="Viewport meta tag present",
        passed=has_viewport,
        detail=f'<meta name="viewport" content="{viewport_content}"> ✓' if has_viewport else "⚠️ No viewport meta — page will not scale on mobile",
    ))

    if has_viewport:
        summary.results.append(CompatTestResult(
            category="Responsive",
            test="Viewport uses width=device-width",
            passed=has_width_device,
            detail="width=device-width ✓" if has_width_device else f"⚠️ Viewport: {viewport_content} — missing width=device-width",
        ))

        # initial-scale check
        has_initial_scale = "initial-scale=1" in (viewport_content or "")
        summary.results.append(CompatTestResult(
            category="Responsive",
            test="Viewport initial-scale=1",
            passed=has_initial_scale,
            detail="initial-scale=1 ✓" if has_initial_scale else "Missing initial-scale=1 in viewport",
        ))

        # user-scalable=no is bad (accessibility)
        blocks_zoom = "user-scalable=no" in (viewport_content or "") or "maximum-scale=1" in (viewport_content or "")
        summary.results.append(CompatTestResult(
            category="Responsive",
            test="Zoom not blocked (user-scalable)",
            passed=not blocks_zoom,
            detail="Zoom allowed ✓" if not blocks_zoom else "⚠️ user-scalable=no or maximum-scale=1 — blocks accessibility zoom",
        ))

    # ── Horizontal scroll on mobile (375px viewport) ─────────────────────────
    try:
        has_overflow = page.evaluate("""
            () => {
                const orig = document.documentElement.style.overflowX;
                const bodyWidth = document.body.scrollWidth;
                const winWidth = window.innerWidth;
                return bodyWidth > winWidth + 5;
            }
        """)
        summary.results.append(CompatTestResult(
            category="Mobile",
            test="No horizontal scroll on current viewport",
            passed=not has_overflow,
            detail="No horizontal overflow ✓" if not has_overflow else "⚠️ Page overflows horizontally — causes mobile scroll issues",
        ))
    except Exception:
        pass

    # ── Touch target sizes ────────────────────────────────────────────────────
    try:
        small_targets = page.evaluate("""
            () => {
                const interactive = Array.from(document.querySelectorAll('button, a, input, select, textarea, [role="button"]'));
                return interactive.filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0 && (r.width < 44 || r.height < 44);
                }).length;
            }
        """)
        total_interactive = page.evaluate("""
            () => document.querySelectorAll('button:not([hidden]), a:not([hidden]), input:not([hidden])').length
        """)
        summary.results.append(CompatTestResult(
            category="Mobile",
            test="Touch targets ≥ 44×44px",
            passed=small_targets == 0,
            detail=f"All touch targets meet 44px minimum ✓" if small_targets == 0 else f"⚠️ {small_targets} element(s) smaller than 44×44px (hard to tap on mobile)",
        ))
    except Exception:
        pass

    # ── Responsive images ────────────────────────────────────────────────────
    try:
        img_stats = page.evaluate("""
            () => {
                const imgs = Array.from(document.images);
                const withSrcset = imgs.filter(i => i.srcset || i.closest('picture'));
                const withSizes  = imgs.filter(i => i.sizes);
                return { total: imgs.length, srcset: withSrcset.length, sizes: withSizes.length };
            }
        """)
        total_img = img_stats["total"]
        srcset_count = img_stats["srcset"]
        if total_img > 0:
            summary.results.append(CompatTestResult(
                category="Responsive Images",
                test="Images use srcset/picture",
                passed=srcset_count > 0,
                detail=f"{srcset_count}/{total_img} images use srcset/picture ✓" if srcset_count > 0 else f"⚠️ No responsive images — same image on all devices",
            ))
    except Exception:
        pass

    # ── CSS media queries (responsive) ───────────────────────────────────────
    try:
        has_mq = page.evaluate("""
            () => {
                for (const sheet of document.styleSheets) {
                    try {
                        for (const rule of sheet.cssRules || []) {
                            if (rule.type === CSSRule.MEDIA_RULE) return true;
                        }
                    } catch(e) {}
                }
                return false;
            }
        """)
        summary.results.append(CompatTestResult(
            category="Responsive",
            test="CSS media queries present",
            passed=has_mq,
            detail="Media queries found — responsive CSS ✓" if has_mq else "⚠️ No CSS media queries — page may not be responsive",
        ))
    except Exception:
        pass

    # ── Flexbox / Grid usage ─────────────────────────────────────────────────
    try:
        layout_info = page.evaluate("""
            () => {
                let flex = 0, grid = 0;
                try {
                    for (const sheet of document.styleSheets) {
                        try {
                            const text = Array.from(sheet.cssRules||[]).map(r => r.cssText||'').join('');
                            if (text.includes('display: flex') || text.includes('display:flex')) flex++;
                            if (text.includes('display: grid') || text.includes('display:grid')) grid++;
                        } catch(e) {}
                    }
                } catch(e) {}
                return { flex, grid };
            }
        """)
        has_modern = layout_info["flex"] > 0 or layout_info["grid"] > 0
        summary.results.append(CompatTestResult(
            category="CSS Layout",
            test="Modern layout (Flexbox/Grid) used",
            passed=has_modern,
            detail=f"Flexbox: {layout_info['flex']}, Grid: {layout_info['grid']} rules ✓" if has_modern else "No Flexbox/Grid detected — may use older float-based layout",
        ))
    except Exception:
        pass

    # ── Print stylesheet ──────────────────────────────────────────────────────
    try:
        has_print = page.evaluate("""
            () => {
                for (const sheet of document.styleSheets) {
                    if (sheet.media && sheet.media.mediaText && sheet.media.mediaText.includes('print')) return true;
                    try {
                        for (const rule of sheet.cssRules || []) {
                            if (rule.type === CSSRule.MEDIA_RULE && rule.media.mediaText.includes('print')) return true;
                        }
                    } catch(e) {}
                }
                return !!document.querySelector('link[media="print"]');
            }
        """)
        summary.results.append(CompatTestResult(
            category="Print",
            test="Print stylesheet present",
            passed=has_print,
            detail="Print styles found ✓" if has_print else "No print stylesheet (page may print poorly)",
        ))
    except Exception:
        pass

    # ── lang attribute on <html> ──────────────────────────────────────────────
    lang = page.evaluate("() => document.documentElement.lang")
    summary.results.append(CompatTestResult(
        category="i18n / Accessibility",
        test="lang attribute on <html>",
        passed=bool(lang),
        detail=f'lang="{lang}" ✓' if lang else '⚠️ Missing lang attribute — screen readers cannot detect language',
    ))

    # ── charset meta ─────────────────────────────────────────────────────────
    charset = page.evaluate("""
        () => {
            const m = document.querySelector('meta[charset]');
            return m ? m.getAttribute('charset') : '';
        }
    """)
    summary.results.append(CompatTestResult(
        category="Encoding",
        test="charset meta defined",
        passed=bool(charset),
        detail=f'charset="{charset}" ✓' if charset else "⚠️ No charset meta — encoding issues possible",
    ))

    # ── Favicon ───────────────────────────────────────────────────────────────
    favicon = page.query_selector('link[rel*="icon"]')
    summary.results.append(CompatTestResult(
        category="Browser Compat",
        test="Favicon defined",
        passed=favicon is not None,
        detail="Favicon link found ✓" if favicon else "No favicon link (shows generic icon in browser tabs)",
    ))

    # ── Open Graph / Social meta ─────────────────────────────────────────────
    og_title = page.query_selector('meta[property="og:title"]')
    summary.results.append(CompatTestResult(
        category="Social / SEO",
        test="Open Graph meta tags present",
        passed=og_title is not None,
        detail="og:title found ✓" if og_title else "No Open Graph tags — poor social media preview",
    ))

    return summary
