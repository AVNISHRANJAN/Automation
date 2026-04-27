#!/usr/bin/env python3
"""
main.py — WebScanner CLI (Playwright Edition)

Usage:
  python main.py <url> [options]

Modes:
  (default)       Browser-driven QA suite with Excel report + fail screenshots
  --scan-only     Original element scanner (forms, links, buttons)
  --full-test     Run all 11 test categories (recommended)
  --qa-report     Same as default; kept for explicit QA runs

Options:
  --export-json    Save results as JSON in ./reports/
  --export-html    Save results as HTML report in ./reports/
  --headed         Run browser in visible (non-headless) mode
  --max-pages N    QA mode: maximum internal pages to crawl (default: 5)
  --max-controls N QA mode: maximum controls per type per page (default: 8)
  --help           Show this help

Examples:
  python main.py https://hanuai.com
  python main.py https://hanuai.com --qa-report --max-pages 8 --max-controls 12
  python main.py https://github.com/login --full-test --export-html
  python main.py flipkart.com --full-test
  python main.py https://amazon.in --full-test --export-json --export-html
  python main.py https://github.com/login --scan-only
"""

import sys
from src.scanner import WebScanner
from src.reporter import print_report
from src.exporter import export_json, export_html
from src.test_runner import TestRunner
from src.full_reporter import print_full_report
from src.full_exporter import export_full_json, export_full_html, export_full_xlsx
from src.qa_runner import QARunner
from src.qa_exporter import export_qa_xlsx


def show_help():
    print(__doc__)
    sys.exit(0)


def read_int_arg(args: list[str], flag: str, default: int) -> int:
    if flag not in args:
        return default
    idx = args.index(flag)
    try:
        value = int(args[idx + 1])
    except (IndexError, ValueError):
        print(f"❌ {flag} requires a number")
        sys.exit(1)
    if value < 1:
        print(f"❌ {flag} must be greater than 0")
        sys.exit(1)
    return value


def main():
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        show_help()

    url        = args[0]
    headed     = "--headed"      in args
    do_json    = "--export-json" in args
    do_html    = "--export-html" in args
    full_test  = "--full-test"   in args
    scan_only  = "--scan-only"   in args
    qa_report  = "--qa-report"   in args or (not full_test and not scan_only)
    max_pages = read_int_arg(args, "--max-pages", 5)
    max_controls = read_int_arg(args, "--max-controls", 8)

    print(f"\n🌐 WebScanner — Playwright Edition")
    print(f"   Scanning : {url}")
    if qa_report:
        mode_text = "Browser-driven QA Report (Excel + failure screenshots)"
    elif full_test:
        mode_text = "Full Test Suite (11 categories)"
    else:
        mode_text = "Element Scanner"
    print(f"   Mode     : {mode_text}")
    print(f"   Browser  : {'headed (visible)' if headed else 'headless'}\n")

    if qa_report:
        runner = QARunner(headless=not headed, max_pages=max_pages, max_controls_per_type=max_controls)
        try:
            report = runner.run(url, screenshots_dir="screenshots")
        except Exception as e:
            print(f"\n❌ Scan failed: {e}")
            sys.exit(1)

        try:
            xlsx_path = export_qa_xlsx(report, out_dir="reports")
        except Exception as e:
            print(f"\n❌ Excel export failed: {e}")
            sys.exit(1)

        print("✅ QA run completed")
        print(f"   Pages tested     : {report.pages_tested}")
        print(f"   Total test cases : {report.total}")
        print(f"   Passed           : {report.passed}")
        print(f"   Failed           : {report.failed}")
        print(f"   Selectors file   : {report.selector_file_path}")
        print(f"   Excel report     : {xlsx_path}")
        print("   Screenshots dir  : screenshots/ (horizontal screenshots)")

    elif full_test:
        runner = TestRunner(headless=not headed)
        try:
            report = runner.run(url)
        except Exception as e:
            print(f"\n❌ Scan failed: {e}")
            sys.exit(1)

        print_full_report(report)

        # Always generate Excel report
        try:
            xlsx_path = export_full_xlsx(report, out_dir="reports")
            print(f"  📊 Excel report  : {xlsx_path}")
        except Exception as e:
            print(f"  ⚠️  Excel export failed: {e}")

        if do_json:
            path = export_full_json(report)
            print(f"  📁 JSON saved : {path}")

        if do_html:
            path = export_full_html(report)
            print(f"  🌐 HTML saved : {path}")

    else:
        scanner = WebScanner(headless=not headed)
        try:
            result = scanner.scan(url)
        except Exception as e:
            print(f"\n❌ Scan failed: {e}")
            sys.exit(1)

        print_report(result)

        if do_json:
            path = export_json(result)
            print(f"  📁 JSON saved : {path}")

        if do_html:
            path = export_html(result)
            print(f"  🌐 HTML saved : {path}")

    if do_json or do_html:
        print()


if __name__ == "__main__":
    main()
