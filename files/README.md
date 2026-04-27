# WebScanner2 — Playwright-Based Web Automation Testing Tool

A production-quality, Python + Playwright web automation testing suite.  
Crawls any website, detects login pages, performs functional testing, and exports structured Excel/JSON/HTML reports.

---

## Features

| Capability | Details |
|---|---|
| **Login Detection** | Detects password + username/email fields; prompts operator for credentials |
| **Secure Credential Handling** | Credentials entered interactively in terminal — never auto-fetched or stored |
| **Page Crawling** | Discovers and visits up to N internal pages (configurable) |
| **Element Testing** | Buttons, links, dropdowns, inputs, checkboxes, radio buttons, forms |
| **Selector Strategy** | XPath + CSS — full inventory saved to `reports/selectors_*.txt` |
| **Error Screenshots** | Taken **only** for failed steps (not for passes) |
| **Excel Reports** | Structured `.xlsx` with Pass (green) / Fail (red) colour coding |
| **JSON Reports** | Machine-readable structured output |
| **HTML Reports** | Interactive, collapsible dark-mode report |
| **Deduplication** | Each element/link tested at most once per run |
| **Safety Filters** | Skips destructive actions (delete, pay, checkout, upload, logout…) |
| **Console & Network** | Captures JS console errors and failed network requests |

---

## Project Structure

```
WebScaner2/
├── venv/                        # Python virtual environment
├── reports/                     # Generated Excel, JSON, HTML reports
├── screenshots/                 # Failure screenshots (auto-created)
└── files/                       # Source code root
    ├── main.py                  # CLI entry point
    ├── requirements.txt
    ├── pyrightconfig.json
    └── src/
        ├── __init__.py
        ├── scanner.py           # Lightweight element scanner (--scan-only)
        ├── reporter.py          # Console reporter for scan-only mode
        ├── exporter.py          # JSON/HTML exporter for scan-only mode
        ├── qa_runner.py         # ★ Main QA runner (default mode)
        ├── qa_logger.py         # Real-time coloured step logger
        ├── qa_exporter.py       # Excel exporter for QA mode
        ├── test_runner.py       # Full-test orchestrator (--full-test)
        ├── full_reporter.py     # Console reporter for full-test mode
        ├── full_exporter.py     # Excel/JSON/HTML for full-test mode
        └── testers/             # 11 specialist test modules
            ├── form_tester.py
            ├── nav_tester.py
            ├── auth_tester.py
            ├── session_tester.py
            ├── search_tester.py
            ├── payment_tester.py
            ├── file_tester.py
            ├── error_tester.py
            ├── performance_tester.py
            ├── security_tester.py
            └── compat_tester.py
```

---

## Installation

### Prerequisites
- Python 3.11+
- pip

### 1 — Create and activate a virtual environment

```bash
cd /home/avnish/Documents/WebScaner2

python3 -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate         # Windows
```

### 2 — Install Python dependencies

```bash
pip install -r files/requirements.txt
```

### 3 — Install Playwright browser binaries

```bash
playwright install chromium
```

> Only Chromium is required.  Run `playwright install` to install all browsers.

---

## Running the Tool

All commands must be run from the **`files/`** directory with the venv active:

```bash
cd /home/avnish/Documents/WebScaner2/files
source ../venv/bin/activate
```

### Mode 1 — Default QA Report (recommended)

```bash
python main.py https://example.com
```

- Crawls up to 5 pages (configurable)
- Runs full functional test suite per page
- Detects login pages and prompts for credentials
- Exports `reports/qa_report_*.xlsx`
- Saves `reports/selectors_*.txt`
- Screenshots only on failures → `screenshots/`

### Mode 2 — Full Test Suite (11 categories)

```bash
python main.py https://example.com --full-test
```

Runs 11 specialist modules:
`Form`, `Navigation`, `Authentication`, `Session`, `Search`,
`Payment`, `File`, `Error Handling`, `Performance`, `Security`, `Compatibility`

```bash
# With all exports
python main.py https://example.com --full-test --export-json --export-html
```

### Mode 3 — Element Scan Only

```bash
python main.py https://example.com --scan-only
```

Lightweight scan listing forms, links, and buttons only.

---

## All CLI Options

```
python main.py <url> [options]

Positional:
  url                   Website URL (http/https prefix optional)

Options:
  --headed              Run browser in visible (non-headless) mode
  --scan-only           Lightweight element scan only
  --full-test           Run all 11 specialist test categories
  --qa-report           Same as default QA run (explicit flag)
  --export-json         Also save a JSON report in ./reports/
  --export-html         Also save an HTML report in ./reports/
  --max-pages N         Max internal pages to crawl (default: 5)
  --max-controls N      Max controls per type per page (default: 8)
  --help / -h           Show this help
```

### Examples

```bash
# Basic QA scan
python main.py https://hanuai.com

# Login site — browser visible so you can observe the session
python main.py https://github.com/login --headed

# Deep crawl with more pages
python main.py https://mysite.com --max-pages 10 --max-controls 15

# Full test + all export formats
python main.py https://amazon.in --full-test --export-json --export-html

# Minimal scan, no interaction
python main.py https://example.com --scan-only --export-json
```

---

## Login Detection Flow

When the landing page contains both a password field and a username/email field:

1. The runner prints a banner in the terminal
2. Prompts: `Username / Email :` (plain text)
3. Prompts: `Password         :` (hidden input via `getpass`)
4. If you press Enter without typing → login is skipped, test continues unauthenticated
5. If credentials are provided → fills fields, clicks submit, waits for navigation
6. Login success is detected by: URL change **or** password field disappearing
7. The authenticated session is shared for all subsequent crawled pages

> **Security note:** Credentials are typed interactively and are never read from any file, environment variable, browser storage, or keychain.

---

## Output Files

| File | Description |
|---|---|
| `reports/qa_report_<host>_<ts>.xlsx` | Excel QA report (Pass/Fail colour coded) |
| `reports/selectors_<host>_<ts>.txt` | XPath + CSS selector inventory |
| `reports/fullreport_<host>_<ts>.xlsx` | Excel report for `--full-test` mode |
| `reports/fullreport_<host>_<ts>.json` | JSON report for `--full-test` mode |
| `reports/fullreport_<host>_<ts>.html` | HTML report for `--full-test` mode |
| `screenshots/<scenario>_<ts>.png` | Screenshot captured on test failure |

### Excel Report Columns (QA mode)

| Column | Content |
|---|---|
| Test Case ID | `TC_001`, `TC_002`, … |
| Test Scenario | Human-readable description of what was tested |
| Steps to Execute | Numbered steps with XPath / CSS selectors |
| Expected Result | What a passing outcome looks like |
| Actual Result | What actually happened |
| Status | `Pass` (green) / `Fail` (red) |
| Screenshot | Absolute path to failure screenshot (empty for passes) |

---

## Troubleshooting

**`ImportError: No module named 'src'`**  
→ Make sure you run `python main.py` from inside the `files/` directory, not from `WebScaner2/`.

**`playwright: command not found`**  
→ Activate the venv first: `source ../venv/bin/activate`

**Browser doesn't launch**  
→ Run `playwright install chromium` to download the browser binary.

**Page times out**  
→ The site may block bots. Try `--headed` so the browser runs in visible mode.

**Login not detected**  
→ Some SPAs render the login form asynchronously. Try `--headed` and increase `--max-pages`.

---

## Requirements

```
playwright>=1.40.0
openpyxl>=3.1.2
```

`openpyxl` is optional — if not installed, reports are still generated using a built-in stdlib XLSX writer (no colour formatting).
