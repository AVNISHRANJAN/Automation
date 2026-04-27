"""reporter.py - Terminal output for default element scanner mode."""


def _print_section(title: str):
    print("\n" + "-" * 64)
    print(title)
    print("-" * 64)


def print_report(result):
    print("\n" + "=" * 64)
    print("WebScanner Element Report")
    print("=" * 64)
    print(f"URL       : {result.url}")
    print(f"Final URL : {result.final_url}")
    print(f"Title     : {result.page_title or '(no title)'}")
    print(f"Time      : {result.scan_time_s}s")

    _print_section("Summary")
    print(f"Forms   : {result.total_forms}")
    print(f"Links   : {result.total_links}")
    print(f"Buttons : {result.total_buttons}")

    _print_section("Forms")
    if not result.forms:
        print("No forms found")
    else:
        for idx, form in enumerate(result.forms[:20], start=1):
            action = form.action if form.action else "(same page)"
            print(f"{idx:2}. method={form.method:<6} fields={form.fields:<3} action={action}")

    _print_section("Links (first 30)")
    if not result.links:
        print("No links found")
    else:
        for idx, link in enumerate(result.links[:30], start=1):
            print(f"{idx:2}. [{link.kind}] {link.text} -> {link.href}")

    _print_section("Buttons (first 20)")
    if not result.buttons:
        print("No buttons found")
    else:
        for idx, button in enumerate(result.buttons[:20], start=1):
            print(f"{idx:2}. type={button.type:<8} text={button.text}")

    print()
