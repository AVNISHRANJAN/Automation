"""
search_tester.py — Search Function Testing (Category 15)

Tests:
  - Search bar presence
  - Search input attributes (placeholder, type=search, autocomplete)
  - Search form action/method
  - Filter/sort controls presence
  - Search results container detection
  - Autocomplete/suggestions dropdown
"""

from playwright.sync_api import Page
from dataclasses import dataclass, field


@dataclass
class SearchTestResult:
    category: str
    test: str
    passed: bool
    detail: str


@dataclass
class SearchTestSummary:
    results: list[SearchTestResult] = field(default_factory=list)
    has_search: bool = False
    search_inputs: list[dict] = field(default_factory=list)

    @property
    def passed(self): return [r for r in self.results if r.passed]
    @property
    def failed(self): return [r for r in self.results if not r.passed]


def run_search_tests(page: Page) -> SearchTestSummary:
    summary = SearchTestSummary()

    # ── Search bar detection ─────────────────────────────────────────────────
    search_selectors = [
        'input[type="search"]',
        'input[name="q"]',
        'input[name="search"]',
        'input[name="query"]',
        'input[placeholder*="search" i]',
        'input[aria-label*="search" i]',
        '[role="search"] input',
        'input[id*="search" i]',
        'input[class*="search" i]',
    ]

    found_inputs = []
    seen_els = set()
    for sel in search_selectors:
        for el in page.query_selector_all(f'{sel}:visible'):
            try:
                el_id = el.get_attribute("id") or el.get_attribute("name") or str(id(el))
                if el_id in seen_els:
                    continue
                seen_els.add(el_id)
                found_inputs.append({
                    "element": el,
                    "type": el.get_attribute("type") or "text",
                    "name": el.get_attribute("name") or "",
                    "placeholder": el.get_attribute("placeholder") or "",
                    "aria_label": el.get_attribute("aria-label") or "",
                    "autocomplete": el.get_attribute("autocomplete") or "",
                    "id": el.get_attribute("id") or "",
                })
            except Exception:
                pass

    summary.has_search = len(found_inputs) > 0
    summary.search_inputs = [{k: v for k, v in inp.items() if k != "element"} for inp in found_inputs]

    summary.results.append(SearchTestResult(
        category="Search Bar",
        test="Search input present",
        passed=summary.has_search,
        detail=f"Found {len(found_inputs)} search input(s)" if summary.has_search else "No search bar detected on this page",
    ))

    if found_inputs:
        for inp in found_inputs[:3]:
            el = inp["element"]
            name = inp["name"] or inp["id"] or "search"

            # type=search for semantics
            summary.results.append(SearchTestResult(
                category="Search Semantics",
                test=f"type=search used ({name})",
                passed=inp["type"] == "search",
                detail='type="search" ✓ — semantic search input' if inp["type"] == "search" else f'type="{inp["type"]}" — consider type="search"',
            ))

            # role=search on parent
            try:
                parent_role = el.evaluate("el => el.closest('[role]')?.getAttribute('role')")
                has_search_role = parent_role == "search"
                summary.results.append(SearchTestResult(
                    category="Search Accessibility",
                    test=f"role=search on parent ({name})",
                    passed=has_search_role,
                    detail='role="search" on container ✓' if has_search_role else 'No role="search" container (accessibility improvement)',
                ))
            except Exception:
                pass

            # placeholder text
            summary.results.append(SearchTestResult(
                category="Search UX",
                test=f"Search placeholder text ({name})",
                passed=bool(inp["placeholder"]),
                detail=f'placeholder="{inp["placeholder"]}" ✓' if inp["placeholder"] else "No placeholder — user may not know it's a search field",
            ))

            # autocomplete
            ac = inp["autocomplete"]
            good_ac = ac in ("on", "search", "off", "")
            summary.results.append(SearchTestResult(
                category="Search UX",
                test=f"Autocomplete ({name})",
                passed=True,
                detail=f"autocomplete={ac or 'not set'} (browser default)",
            ))

            # Submit button near search
            try:
                parent_form = el.evaluate("el => el.closest('form')")
                if parent_form:
                    submit = page.evaluate("""el => {
                        const form = el.closest('form');
                        return form ? !!form.querySelector('button[type="submit"], input[type="submit"], button:not([type])') : false;
                    }""", el)
                    summary.results.append(SearchTestResult(
                        category="Search UX",
                        test=f"Submit button in search form ({name})",
                        passed=submit,
                        detail="Search submit button found ✓" if submit else "No submit button in search form",
                    ))

                    # Form method
                    method = page.evaluate("el => el.closest('form')?.getAttribute('method') || 'get'", el)
                    summary.results.append(SearchTestResult(
                        category="Search Form",
                        test=f"Search form method ({name})",
                        passed=method.lower() in ("get", ""),
                        detail=f'method="{method}" ✓ — GET is correct for search' if method.lower() in ("get", "") else f'⚠️ method="{method}" — search forms should use GET',
                    ))
            except Exception:
                pass

    # ── Filter/sort controls ─────────────────────────────────────────────────
    filter_selectors = [
        'select[name*="sort" i]', 'select[name*="filter" i]', 'select[id*="sort" i]',
        '[class*="filter" i] select', '[class*="sort" i] select',
        'input[type="checkbox"][name*="filter" i]',
        '[aria-label*="filter" i]', '[aria-label*="sort" i]',
        'button:text-matches("filter|sort", "i")',
    ]
    filter_found = False
    for sel in filter_selectors:
        try:
            if page.query_selector(f'{sel}:visible'):
                filter_found = True
                break
        except Exception:
            pass

    summary.results.append(SearchTestResult(
        category="Filters",
        test="Filter / sort controls present",
        passed=filter_found,
        detail="Filter/sort controls found ✓" if filter_found else "No filter or sort controls detected (may appear after search)",
    ))

    # ── Search results container ─────────────────────────────────────────────
    result_selectors = [
        '[class*="search-results" i]', '[id*="search-results" i]',
        '[class*="results" i]', '[role="main"] ul', '[aria-label*="results" i]',
    ]
    results_found = False
    for sel in result_selectors:
        try:
            if page.query_selector(sel):
                results_found = True
                break
        except Exception:
            pass

    summary.results.append(SearchTestResult(
        category="Search Results",
        test="Search results container present",
        passed=results_found,
        detail="Results container found ✓" if results_found else "No search results container (may appear after search is executed)",
    ))

    # ── Autocomplete/suggestions ─────────────────────────────────────────────
    autocomplete_selectors = [
        '[role="listbox"]', '[class*="autocomplete" i]', '[class*="suggestions" i]',
        '[class*="typeahead" i]', '[aria-autocomplete]',
    ]
    ac_found = False
    for sel in autocomplete_selectors:
        try:
            if page.query_selector(sel):
                ac_found = True
                break
        except Exception:
            pass

    summary.results.append(SearchTestResult(
        category="Autocomplete",
        test="Autocomplete / suggestions widget",
        passed=ac_found,
        detail="Autocomplete widget detected ✓" if ac_found else "No autocomplete widget (may appear on typing)",
    ))

    return summary
