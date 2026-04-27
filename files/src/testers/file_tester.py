"""
file_tester.py — File Upload / Download Testing (Category 17)

Tests:
  - File upload inputs present
  - Accepted file types defined (accept attribute)
  - File size limit hints
  - Multiple file upload support
  - Download links detected
  - Download file types (PDF, images, docs, etc.)
  - Drag-and-drop upload zone detection
"""

from playwright.sync_api import Page
from dataclasses import dataclass, field


@dataclass
class FileTestResult:
    category: str
    test: str
    passed: bool
    detail: str


@dataclass
class FileTestSummary:
    results: list[FileTestResult] = field(default_factory=list)
    upload_inputs: list[dict] = field(default_factory=list)
    download_links: list[dict] = field(default_factory=list)

    @property
    def passed(self): return [r for r in self.results if r.passed]
    @property
    def failed(self): return [r for r in self.results if not r.passed]


DOWNLOAD_EXTENSIONS = [
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".tar", ".gz", ".csv", ".txt", ".json",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".mp4", ".mp3",
    ".apk", ".exe", ".dmg", ".iso",
]

DANGEROUS_UPLOAD_TYPES = [".php", ".js", ".exe", ".sh", ".bat", ".cmd", ".ps1", ".asp", ".aspx"]


def run_file_tests(page: Page) -> FileTestSummary:
    summary = FileTestSummary()

    # ── File upload inputs ───────────────────────────────────────────────────
    for el in page.query_selector_all('input[type="file"]:not([style*="display:none"]), input[type="file"]:visible'):
        try:
            name     = el.get_attribute("name") or el.get_attribute("id") or "file"
            accept   = el.get_attribute("accept") or ""
            multiple = el.get_attribute("multiple") is not None
            required = el.get_attribute("required") is not None

            summary.upload_inputs.append({
                "name": name, "accept": accept,
                "multiple": multiple, "required": required,
            })

            # accept attribute defined?
            summary.results.append(FileTestResult(
                category="Upload",
                test=f"File type restriction (accept): {name}",
                passed=bool(accept),
                detail=f"accept=\"{accept}\" ✓" if accept else "⚠️ No accept attribute — any file type can be uploaded",
            ))

            # Dangerous types NOT in accept?
            if accept:
                dangerous_allowed = [ext for ext in DANGEROUS_UPLOAD_TYPES if ext in accept.lower()]
                summary.results.append(FileTestResult(
                    category="Upload Security",
                    test=f"Dangerous types not accepted: {name}",
                    passed=len(dangerous_allowed) == 0,
                    detail="No dangerous file types in accept ✓" if not dangerous_allowed else f"⚠️ Dangerous types allowed: {dangerous_allowed}",
                ))

            # Multiple files?
            summary.results.append(FileTestResult(
                category="Upload",
                test=f"Multiple file upload: {name}",
                passed=True,
                detail="multiple=true (bulk upload supported)" if multiple else "Single file only",
            ))

            # Label?
            el_id = el.get_attribute("id")
            label_el = page.query_selector(f'label[for="{el_id}"]') if el_id else None
            summary.results.append(FileTestResult(
                category="Upload UX",
                test=f"Upload field has label: {name}",
                passed=label_el is not None,
                detail="Label found ✓" if label_el else "No label for file input (UX gap)",
            ))
        except Exception:
            pass

    if not summary.upload_inputs:
        summary.results.append(FileTestResult(
            category="Upload",
            test="File upload inputs detected",
            passed=False,
            detail="No file upload inputs found on this page",
        ))

    # ── Drag and drop zones ──────────────────────────────────────────────────
    dnd_selectors = [
        '[class*="dropzone" i]', '[class*="drop-zone" i]', '[class*="drag-drop" i]',
        '[id*="dropzone" i]', '[aria-label*="drag" i]', '[data-dropzone]',
    ]
    dnd_found = False
    for sel in dnd_selectors:
        try:
            if page.query_selector(sel):
                dnd_found = True
                break
        except Exception:
            pass

    if summary.upload_inputs:
        summary.results.append(FileTestResult(
            category="Upload UX",
            test="Drag-and-drop upload zone",
            passed=dnd_found,
            detail="Drag-drop zone found ✓" if dnd_found else "No drag-drop zone (only click-to-upload available)",
        ))

    # ── Upload progress indicator ────────────────────────────────────────────
    if summary.upload_inputs:
        progress_selectors = ['progress', '[role="progressbar"]', '[class*="progress" i]', '[class*="upload-progress" i]']
        progress_found = any(
            page.query_selector(sel) is not None for sel in progress_selectors
        )
        summary.results.append(FileTestResult(
            category="Upload UX",
            test="Upload progress indicator",
            passed=progress_found,
            detail="Progress bar found ✓" if progress_found else "No upload progress indicator (large files may confuse users)",
        ))

    # ── Download links ────────────────────────────────────────────────────────
    for el in page.query_selector_all("a[href]:visible"):
        try:
            href = el.get_attribute("href") or ""
            download_attr = el.get_attribute("download")
            text = el.inner_text().strip()[:40] or href[:40]

            is_download = (
                download_attr is not None or
                any(href.lower().endswith(ext) for ext in DOWNLOAD_EXTENSIONS)
            )

            if is_download:
                ext = next((ext for ext in DOWNLOAD_EXTENSIONS if href.lower().endswith(ext)), "unknown")
                summary.download_links.append({"text": text, "href": href, "ext": ext})
        except Exception:
            pass

    if summary.download_links:
        summary.results.append(FileTestResult(
            category="Download",
            test="Download links detected",
            passed=True,
            detail=f"Found {len(summary.download_links)} download link(s): {', '.join(set(d['ext'] for d in summary.download_links[:5]))}",
        ))

        # Check for download attribute
        links_with_attr = [d for d in summary.download_links if d.get("ext") != "unknown"]
        summary.results.append(FileTestResult(
            category="Download",
            test="Download links use file extensions",
            passed=len(links_with_attr) > 0,
            detail=f"{len(links_with_attr)} links have recognizable file extensions ✓",
        ))
    else:
        summary.results.append(FileTestResult(
            category="Download",
            test="Download links detected",
            passed=False,
            detail="No download links found on this page",
        ))

    # ── File size limit hints ────────────────────────────────────────────────
    try:
        page_text = page.inner_text("body").lower()
        size_hints = any(kw in page_text for kw in [
            "max file", "maximum file", "file size", "size limit", "mb limit",
            "upload limit", "allowed size", "max size"
        ])
        if summary.upload_inputs:
            summary.results.append(FileTestResult(
                category="Upload UX",
                test="File size limit communicated to user",
                passed=size_hints,
                detail="File size limit hint found ✓" if size_hints else "No file size limit shown to user (may cause silent failures)",
            ))
    except Exception:
        pass

    return summary
