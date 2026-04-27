"""scanner.py - Element scanner used by the default CLI mode.

Scans a page for high-level elements:
- forms (method/action and field count)
- links (text, href, internal vs external)
- buttons (text/type)
"""

from dataclasses import dataclass, field, asdict
from time import time
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright


@dataclass
class FormInfo:
    method: str
    action: str
    fields: int


@dataclass
class LinkInfo:
    text: str
    href: str
    kind: str


@dataclass
class ButtonInfo:
    text: str
    type: str


@dataclass
class ScanResult:
    url: str
    final_url: str
    page_title: str
    scan_time_s: float
    forms: list[FormInfo] = field(default_factory=list)
    links: list[LinkInfo] = field(default_factory=list)
    buttons: list[ButtonInfo] = field(default_factory=list)

    @property
    def total_forms(self) -> int:
        return len(self.forms)

    @property
    def total_links(self) -> int:
        return len(self.links)

    @property
    def total_buttons(self) -> int:
        return len(self.buttons)

    def to_dict(self) -> dict:
        return asdict(self)


class WebScanner:
    def __init__(self, headless: bool = True, timeout: int = 20000):
        self.headless = headless
        self.timeout = timeout

    def scan(self, url: str) -> ScanResult:
        if not url.startswith("http"):
            url = "https://" + url

        t0 = time()
        forms: list[FormInfo] = []
        links: list[LinkInfo] = []
        buttons: list[ButtonInfo] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
                page.wait_for_load_state("networkidle", timeout=8000)
            except PWTimeout:
                pass

            final_url = page.url
            base_host = urlparse(final_url).netloc
            page_title = page.title()

            for form in page.query_selector_all("form"):
                try:
                    method = (form.get_attribute("method") or "GET").upper()
                    action = form.get_attribute("action") or ""
                    fields = len(form.query_selector_all("input, select, textarea"))
                    forms.append(FormInfo(method=method, action=action, fields=fields))
                except Exception:
                    continue

            for a in page.query_selector_all("a[href]"):
                try:
                    href = (a.get_attribute("href") or "").strip()
                    if not href:
                        continue
                    text = (a.inner_text() or "").strip().replace("\n", " ")
                    if not text:
                        text = "(no text)"

                    if href.startswith("http"):
                        link_host = urlparse(href).netloc
                        kind = "internal" if link_host == base_host else "external"
                    else:
                        kind = "internal"

                    links.append(LinkInfo(text=text[:100], href=href, kind=kind))
                except Exception:
                    continue

            for btn in page.query_selector_all("button, input[type='button'], input[type='submit'], input[type='reset']"):
                try:
                    tag = btn.evaluate("el => el.tagName.toLowerCase()")
                    btype = (btn.get_attribute("type") or ("button" if tag == "button" else "input")).lower()
                    text = (btn.inner_text() or btn.get_attribute("value") or "").strip()
                    if not text:
                        text = "(no text)"
                    buttons.append(ButtonInfo(text=text[:100], type=btype))
                except Exception:
                    continue

            browser.close()

        return ScanResult(
            url=url,
            final_url=final_url,
            page_title=page_title,
            scan_time_s=round(time() - t0, 2),
            forms=forms,
            links=links,
            buttons=buttons,
        )
