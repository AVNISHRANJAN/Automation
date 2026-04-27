"""
full_reporter.py — Terminal report printer for all 11 test categories
"""

from src.test_runner import TestReport

R    = "\033[0m"
BOLD = "\033[1m"
DIM  = "\033[2m"
GREEN   = "\033[32m"
RED     = "\033[31m"
YELLOW  = "\033[33m"
BLUE    = "\033[34m"
CYAN    = "\033[36m"
MAGENTA = "\033[35m"
WHITE   = "\033[37m"
BG_RED  = "\033[41m"

def c(color, text): return f"{color}{text}{R}"

LINE = "─" * 66


def _section_header(number: str, title: str, passed: int, total: int):
    ratio = passed / total if total else 1
    bar_color = GREEN if ratio >= 0.8 else YELLOW if ratio >= 0.5 else RED
    print(f"\n{c(CYAN, LINE)}")
    print(f"  {c(BOLD, c(WHITE, f'{number} {title}'))}  {c(bar_color, f'{passed}/{total} passed')}")
    print(c(DIM, "  " + "─" * 50))


def _result_row(result):
    icon = c(GREEN, "  ✓") if result.passed else c(RED, "  ✗")
    sev  = ""
    if hasattr(result, "severity") and not result.passed:
        sev_colors = {"critical": BG_RED, "high": RED, "medium": YELLOW, "low": DIM}
        sev = f" {c(sev_colors.get(result.severity, ''), f'[{result.severity.upper()}]')}"
    print(f"{icon}{sev} {c(BOLD, result.test)}")
    detail_color = DIM if result.passed else YELLOW
    print(f"     {c(detail_color, result.detail[:100])}")


def print_full_report(report: TestReport):
    print(f"\n{c(CYAN, LINE)}")
    print(f"{c(CYAN, '  🌐  WebScanner — Full Test Report')}")
    print(f"  URL   : {c(WHITE, report.url)}")
    print(f"  Title : {c(DIM, report.page_title or '(no title)')}")
    print(f"  Time  : {c(DIM, f'{report.scan_time_s}s')}")
    print(c(CYAN, LINE))

    modules = [
        ("11", "Form Testing",          report.form),
        ("12", "Navigation Testing",    report.nav),
        ("13", "Authentication Testing",report.auth),
        ("14", "Session Testing",       report.session),
        ("15", "Search Testing",        report.search),
        ("16", "Payment Testing",       report.payment),
        ("17", "File Upload/Download",  report.files),
        ("18", "Error Handling",        report.errors),
        ("19", "Performance Testing",   report.performance),
        ("20", "Security Testing",      report.security),
        ("21", "Compatibility Testing", report.compat),
    ]

    for num, title, mod in modules:
        results = mod.results
        if not results:
            continue
        passed = len(mod.passed)
        total  = len(results)
        _section_header(num + ".", title, passed, total)
        for r in results:
            _result_row(r)

    # ── Final summary ────────────────────────────────────────────────────────
    print(f"\n{c(CYAN, LINE)}")
    print(c(BOLD, c(WHITE, "  📊  OVERALL TEST SUMMARY")))
    print(c(CYAN, LINE))

    for num, title, mod in modules:
        results = mod.results
        if not results:
            continue
        passed = len(mod.passed)
        total  = len(results)
        ratio  = passed / total if total else 1
        bar_color = GREEN if ratio >= 0.8 else YELLOW if ratio >= 0.5 else RED
        bar = "█" * round(ratio * 20)
        print(f"  {num}.{title:<28} {c(bar_color, f'{passed:2}/{total:2}')}  {c(bar_color, bar)}")

    score = report.score
    score_color = GREEN if score >= 80 else YELLOW if score >= 50 else RED
    print(f"\n  {c(BOLD, 'Overall Score')}  :  {c(score_color, c(BOLD, f'{score}%'))}  ({report.total_passed}/{report.total_tests} tests passed)")

    # Critical/high failures
    crit = [r for r in report.all_results if not r.passed and hasattr(r, 'severity') and r.severity == 'critical']
    high = [r for r in report.all_results if not r.passed and hasattr(r, 'severity') and r.severity == 'high']
    if crit:
        print(f"\n  {c(BG_RED, f'  🚨 {len(crit)} CRITICAL issue(s) — fix immediately!  ')}")
        for r in crit:
            print(f"     {c(RED, '→')} {r.test}")
    if high:
        print(f"\n  {c(RED, f'  ⚠️  {len(high)} HIGH severity issue(s):'  )}")
        for r in high[:5]:
            print(f"     {c(YELLOW, '→')} {r.test}")

    print(c(CYAN, LINE))
    print()
