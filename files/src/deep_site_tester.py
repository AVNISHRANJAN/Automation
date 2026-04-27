#!/usr/bin/env python3
"""Rule-based deep website tester.

Features:
- Crawls internal pages (bounded)
- Extracts IDs, CSS selectors, and XPath selectors into one TXT file
- Clicks links/buttons/clickables for broad interaction coverage
- Performs basic login-page focused checks
- Captures horizontal screenshots during the run
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import Page, sync_playwright


@dataclass
class SelectorEntry:
    page_url: str
    element_label: str
    selector_type: str
    selector: str


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_name(text: str) -> str:
    out = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)[:120].strip("_") or "item"


def is_internal(base_host: str, url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if not parsed.scheme:
        return True
    return parsed.netloc == base_host


def make_dirs(root: Path) -> tuple[Path, Path]:
    reports_dir = root / "reports"
    shots_dir = root / "screenshots" / "horizontal"
    reports_dir.mkdir(parents=True, exist_ok=True)
    shots_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir, shots_dir


def take_shot(page: Page, shots_dir: Path, label: str) -> str:
    filename = f"{safe_name(label)}_{now_stamp()}.png"
    out = shots_dir / filename
    page.screenshot(path=str(out), full_page=True)
    return str(out)


def js_get_selectors() -> str:
    return """
() => {
  function cssPath(el) {
    if (!(el instanceof Element)) return "";
    if (el.id) return `#${el.id}`;
    const path = [];
    while (el && el.nodeType === Node.ELEMENT_NODE) {
      let selector = el.nodeName.toLowerCase();
      if (el.className && typeof el.className === 'string') {
        const cls = el.className.trim().split(/\\s+/).slice(0,2).join('.');
        if (cls) selector += '.' + cls;
      }
      let sib = el;
      let nth = 1;
      while ((sib = sib.previousElementSibling)) {
        if (sib.nodeName.toLowerCase() === el.nodeName.toLowerCase()) nth++;
      }
      selector += `:nth-of-type(${nth})`;
      path.unshift(selector);
      el = el.parentElement;
      if (path.length >= 5) break;
    }
    return path.join(' > ');
  }

  function xpath(el) {
    if (!el || el.nodeType !== 1) return "";
    if (el.id) return `//*[@id="${el.id}"]`;
    const parts = [];
    while (el && el.nodeType === 1) {
      let ix = 1;
      let sib = el.previousSibling;
      while (sib) {
        if (sib.nodeType === 1 && sib.nodeName === el.nodeName) ix++;
        sib = sib.previousSibling;
      }
      parts.unshift(`${el.nodeName.toLowerCase()}[${ix}]`);
      el = el.parentNode;
      if (parts.length >= 8) break;
    }
    return '/' + parts.join('/');
  }

  const out = [];
  const nodes = Array.from(document.querySelectorAll('a,button,input,select,textarea,[role="button"],[onclick],h1,h2,h3,h4,h5,h6'));
  for (const el of nodes) {
    const txt = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().slice(0, 80);
    const id = el.id ? `#${el.id}` : '';
    const name = el.getAttribute('name') || '';
    const aria = el.getAttribute('aria-label') || '';
    out.push({
      tag: el.tagName.toLowerCase(),
      text: txt,
      id_selector: id,
      name_selector: name ? `[name="${name}"]` : '',
      aria_selector: aria ? `[aria-label="${aria}"]` : '',
      css_selector: cssPath(el),
      xpath_selector: xpath(el),
      href: el.getAttribute('href') || ''
    });
  }
  return out;
}
"""


def collect_entries(page: Page) -> list[SelectorEntry]:
    entries: list[SelectorEntry] = []
    data = page.evaluate(js_get_selectors())
    url = page.url
    for item in data:
        label = f"{item.get('tag','')} | {item.get('text','(no text)')}"
        for stype, sval in (
            ("ID", item.get("id_selector", "")),
            ("NAME", item.get("name_selector", "")),
            ("ARIA", item.get("aria_selector", "")),
            ("CSS", item.get("css_selector", "")),
            ("XPATH", item.get("xpath_selector", "")),
        ):
            sval = (sval or "").strip()
            if sval:
                entries.append(SelectorEntry(url, label, stype, sval))
    return entries


def write_selector_txt(out_path: Path, rows: Iterable[SelectorEntry]) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        f.write("Website Selector Extraction\n")
        f.write(f"Generated At: {datetime.now().isoformat()}\n")
        f.write("=" * 96 + "\n\n")
        for r in rows:
            f.write(f"PAGE: {r.page_url}\n")
            f.write(f"ELEMENT: {r.element_label}\n")
            f.write(f"TYPE: {r.selector_type}\n")
            f.write(f"SELECTOR: {r.selector}\n")
            f.write("-" * 96 + "\n")


def test_selectors_one_by_one(page: Page, rows: list[SelectorEntry], shots_dir: Path, max_checks: int = 120) -> list[str]:
    logs: list[str] = []
    checked = 0
    for row in rows:
        if checked >= max_checks:
            logs.append(f"Selector checks capped at {max_checks} to keep run bounded")
            break
        try:
            if row.selector_type == "XPATH":
                count = page.locator(f"xpath={row.selector}").count()
            else:
                count = page.locator(row.selector).count()
            ok = count > 0
            logs.append(f"[{ 'PASS' if ok else 'FAIL' }] {row.selector_type}: {row.selector} -> count={count}")
            if not ok:
                take_shot(page, shots_dir, f"selector_fail_{safe_name(row.selector_type)}")
        except Exception as exc:
            logs.append(f"[FAIL] {row.selector_type}: {row.selector} -> {str(exc)[:120]}")
            take_shot(page, shots_dir, f"selector_error_{safe_name(row.selector_type)}")
        checked += 1
    return logs


def click_all_links_and_buttons(
    page: Page,
    base_url: str,
    shots_dir: Path,
    max_links: int = 20,
    max_clicks: int = 40,
) -> list[str]:
    logs: list[str] = []
    base_host = urlparse(base_url).netloc

    # Click all hyperlinks by opening each destination URL directly.
    hrefs = []
    for a in page.query_selector_all("a[href]"):
        href = (a.get_attribute("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue
        full = href if href.startswith("http") else urljoin(page.url, href)
        if is_internal(base_host, full):
            hrefs.append(full)
    hrefs = list(dict.fromkeys(hrefs))[:max_links]

    for i, link in enumerate(hrefs, start=1):
        try:
            page.goto(link, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_load_state("networkidle", timeout=8000)
            logs.append(f"[PASS] Hyperlink visit {i}: {link}")
            take_shot(page, shots_dir, f"link_visit_{i}")
        except Exception as exc:
            logs.append(f"[FAIL] Hyperlink visit {i}: {link} -> {str(exc)[:120]}")
            take_shot(page, shots_dir, f"link_visit_fail_{i}")

    # Return to base page and click visible clickable elements.
    page.goto(base_url, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_load_state("networkidle", timeout=8000)

    clickables = page.locator("button:visible, [role='button']:visible, input[type='button']:visible, input[type='submit']:visible, [onclick]:visible, a:visible")
    total = min(clickables.count(), max_clicks)
    for i in range(total):
        try:
            target = clickables.nth(i)
            label = (target.inner_text() or target.get_attribute("aria-label") or "").strip()[:60]
            target.click(timeout=5000)
            page.wait_for_timeout(400)
            logs.append(f"[PASS] Clickable {i+1}: {label or '(no text)'}")
            take_shot(page, shots_dir, f"clickable_{i+1}")
        except Exception as exc:
            logs.append(f"[FAIL] Clickable {i+1}: {str(exc)[:120]}")
            take_shot(page, shots_dir, f"clickable_fail_{i+1}")
            # Try to keep the test moving by reloading base page.
            try:
                page.goto(base_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_load_state("networkidle", timeout=8000)
                clickables = page.locator("button:visible, [role='button']:visible, input[type='button']:visible, input[type='submit']:visible, [onclick]:visible, a:visible")
            except Exception:
                pass

    return logs


def test_login_page(page: Page, base_url: str, shots_dir: Path) -> list[str]:
    logs: list[str] = []
    base_host = urlparse(base_url).netloc

    candidates = []
    for a in page.query_selector_all("a[href]"):
        href = (a.get_attribute("href") or "").strip()
        txt = (a.inner_text() or "").strip().lower()
        if not href:
            continue
        full = href if href.startswith("http") else urljoin(page.url, href)
        low = full.lower()
        if any(k in low for k in ("login", "signin", "sign-in", "auth")) or any(k in txt for k in ("login", "sign in")):
            if is_internal(base_host, full):
                candidates.append(full)
    candidates = list(dict.fromkeys(candidates))

    if not candidates:
        logs.append("[INFO] No explicit login page detected from homepage links")
        return logs

    login_url = candidates[0]
    logs.append(f"[INFO] Testing login page: {login_url}")
    try:
        page.goto(login_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=8000)
        take_shot(page, shots_dir, "login_page_open")
    except Exception as exc:
        logs.append(f"[FAIL] Unable to open login page: {str(exc)[:120]}")
        take_shot(page, shots_dir, "login_page_open_fail")
        return logs

    email = page.locator("input[type='email'], input[name*='email' i], input[name*='user' i], input[id*='email' i]").first
    password = page.locator("input[type='password']").first
    submit = page.locator("button[type='submit'], input[type='submit'], button:has-text('Login'), button:has-text('Sign in')").first

    try:
        has_email = email.count() > 0
        has_password = password.count() > 0
        has_submit = submit.count() > 0
        logs.append(f"[INFO] Login selectors -> email:{has_email} password:{has_password} submit:{has_submit}")
    except Exception:
        pass

    # Empty submit test
    try:
        if submit.count() > 0:
            submit.click(timeout=5000)
            page.wait_for_timeout(600)
            logs.append("[PASS] Empty login submit interaction executed")
            take_shot(page, shots_dir, "login_empty_submit")
        else:
            logs.append("[FAIL] Login submit control not found")
            take_shot(page, shots_dir, "login_submit_missing")
    except Exception as exc:
        logs.append(f"[FAIL] Empty login submit failed: {str(exc)[:120]}")
        take_shot(page, shots_dir, "login_empty_submit_fail")

    # Invalid credentials test (non-destructive dummy values)
    try:
        if email.count() > 0:
            email.fill("invalid_user@example.com")
        if password.count() > 0:
            password.fill("InvalidPassword123!")
        if submit.count() > 0:
            submit.click(timeout=5000)
            page.wait_for_timeout(800)
            logs.append("[PASS] Invalid credentials login interaction executed")
            take_shot(page, shots_dir, "login_invalid_submit")
    except Exception as exc:
        logs.append(f"[FAIL] Invalid credentials interaction failed: {str(exc)[:120]}")
        take_shot(page, shots_dir, "login_invalid_submit_fail")

    return logs


def crawl_internal(page: Page, start_url: str, max_pages: int = 8) -> list[str]:
    host = urlparse(start_url).netloc
    queue = [start_url]
    seen = set()
    out = []

    while queue and len(out) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_load_state("networkidle", timeout=8000)
            out.append(page.url)
        except PWTimeout:
            continue
        except Exception:
            continue

        for a in page.query_selector_all("a[href]"):
            href = (a.get_attribute("href") or "").strip()
            if not href or href.startswith("#") or href.startswith("javascript"):
                continue
            nxt = href if href.startswith("http") else urljoin(page.url, href)
            if is_internal(host, nxt) and nxt not in seen and nxt not in queue:
                queue.append(nxt)

    return list(dict.fromkeys(out))


def run_deep_site_test(
    target_url: str,
    workspace_root: str = ".",
    max_pages: int = 8,
    max_selector_checks: int = 120,
    max_links: int = 20,
    max_clicks: int = 40,
) -> dict:
    root = Path(workspace_root).resolve()
    reports_dir, shots_dir = make_dirs(root)

    selectors_out = reports_dir / f"selectors_{safe_name(urlparse(target_url).netloc)}_{now_stamp()}.txt"
    runlog_out = reports_dir / f"deep_test_log_{safe_name(urlparse(target_url).netloc)}_{now_stamp()}.txt"

    all_entries: list[SelectorEntry] = []
    logs: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        if not target_url.startswith("http"):
            target_url = "https://" + target_url

        pages = crawl_internal(page, target_url, max_pages=max_pages)
        if not pages:
            pages = [target_url]
        logs.append(f"[INFO] Crawled pages count: {len(pages)}")

        for idx, url in enumerate(pages, start=1):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_load_state("networkidle", timeout=8000)
                take_shot(page, shots_dir, f"page_{idx}_loaded")

                # Verify headings on each page.
                heading_count = page.locator("h1, h2, h3, h4, h5, h6").count()
                logs.append(f"[INFO] Headings on page {idx}: {heading_count} | {url}")
                if heading_count == 0:
                    take_shot(page, shots_dir, f"page_{idx}_no_headings")

                entries = collect_entries(page)
                all_entries.extend(entries)
                logs.append(f"[INFO] Selectors collected from page {idx}: {len(entries)}")
            except Exception as exc:
                logs.append(f"[FAIL] Page visit failed: {url} -> {str(exc)[:120]}")
                take_shot(page, shots_dir, f"page_{idx}_visit_fail")

        # One-by-one selector checks from current page context (homepage).
        page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=8000)
        logs.extend(test_selectors_one_by_one(page, all_entries, shots_dir, max_checks=max_selector_checks))

        # Broad click-through interactions.
        logs.extend(
            click_all_links_and_buttons(
                page,
                target_url,
                shots_dir,
                max_links=max_links,
                max_clicks=max_clicks,
            )
        )

        # Focused login checks.
        logs.extend(test_login_page(page, target_url, shots_dir))

        browser.close()

    # Deduplicate selector rows.
    uniq = {}
    for e in all_entries:
        key = (e.page_url, e.selector_type, e.selector)
        if key not in uniq:
            uniq[key] = e
    final_rows = list(uniq.values())

    write_selector_txt(selectors_out, final_rows)
    with runlog_out.open("w", encoding="utf-8") as f:
        f.write("Deep Site Test Execution Log\n")
        f.write(f"Target URL: {target_url}\n")
        f.write(f"Generated At: {datetime.now().isoformat()}\n")
        f.write("=" * 96 + "\n")
        for line in logs:
            f.write(line + "\n")

    return {
        "target_url": target_url,
        "selectors_file": str(selectors_out),
        "run_log_file": str(runlog_out),
        "screenshots_dir": str(shots_dir),
        "total_selectors": len(final_rows),
        "total_log_lines": len(logs),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Deep site tester")
    parser.add_argument("url", help="Target website URL")
    parser.add_argument("--workspace", default=".", help="Workspace root for /reports and /screenshots")
    parser.add_argument("--max-pages", type=int, default=8, help="Maximum internal pages to crawl")
    parser.add_argument("--max-selector-checks", type=int, default=120, help="Maximum selector checks")
    parser.add_argument("--max-links", type=int, default=20, help="Maximum hyperlink visits")
    parser.add_argument("--max-clicks", type=int, default=40, help="Maximum clickable interactions")
    args = parser.parse_args()

    result = run_deep_site_test(
        args.url,
        workspace_root=args.workspace,
        max_pages=args.max_pages,
        max_selector_checks=args.max_selector_checks,
        max_links=args.max_links,
        max_clicks=args.max_clicks,
    )
    print("Deep site test completed")
    for k, v in result.items():
        print(f"{k}: {v}")