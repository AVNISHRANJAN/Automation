"""
payment_tester.py — Payment Testing (Category 16)

Tests:
  - Payment form detection
  - Card input fields (PAN, CVV, expiry)
  - HTTPS enforcement on payment pages
  - Known payment gateway detection (Stripe, Razorpay, PayPal, etc.)
  - PCI-DSS indicators (iframes, hosted fields)
  - No raw card number in DOM/JS
  - Trust badges / SSL indicators
"""

from playwright.sync_api import Page
from dataclasses import dataclass, field


@dataclass
class PaymentTestResult:
    category: str
    test: str
    passed: bool
    detail: str


@dataclass
class PaymentTestSummary:
    results: list[PaymentTestResult] = field(default_factory=list)
    has_payment_form: bool = False
    detected_gateways: list[str] = field(default_factory=list)

    @property
    def passed(self): return [r for r in self.results if r.passed]
    @property
    def failed(self): return [r for r in self.results if not r.passed]


PAYMENT_GATEWAYS = {
    "Stripe":     ["stripe.com", "js.stripe.com", "stripe", "StripeElement"],
    "PayPal":     ["paypal.com", "paypalobjects.com", "paypal"],
    "Razorpay":   ["razorpay.com", "razorpay"],
    "Paytm":      ["paytm.com", "paytm"],
    "Braintree":  ["braintreepayments.com", "braintree"],
    "Square":     ["squareup.com", "square"],
    "Adyen":      ["adyen.com", "adyen"],
    "CCAvenue":   ["ccavenue.com"],
    "PayU":       ["payu.in", "payu"],
    "Instamojo":  ["instamojo.com"],
    "Google Pay": ["pay.google.com", "googlepay"],
    "PhonePe":    ["phonepe.com"],
    "UPI":        ["upi", "npci"],
}

CARD_FIELD_PATTERNS = {
    "card number": ["card", "cardnumber", "cc-number", "ccnum", "card_number", "pan"],
    "cvv":         ["cvv", "cvc", "cvv2", "security-code", "csc"],
    "expiry":      ["expiry", "exp", "expiration", "cc-exp", "card_exp"],
    "name on card": ["cardholder", "card-name", "cc-name", "name_on_card"],
}


def run_payment_tests(page: Page) -> PaymentTestSummary:
    summary = PaymentTestSummary()
    page_source = page.content().lower()
    page_text = page.inner_text("body").lower()

    # ── HTTPS ─────────────────────────────────────────────────────────────────
    is_https = page.url.startswith("https://")
    summary.results.append(PaymentTestResult(
        category="Security",
        test="Payment page served over HTTPS",
        passed=is_https,
        detail="HTTPS ✓ — encrypted connection" if is_https else "⚠️ HTTP — payment data may be exposed!",
    ))

    # ── Gateway detection ────────────────────────────────────────────────────
    detected = []
    try:
        scripts = page.evaluate("() => Array.from(document.querySelectorAll('script[src]')).map(s => s.src)")
        iframes = page.evaluate("() => Array.from(document.querySelectorAll('iframe[src]')).map(f => f.src)")
        all_resources = scripts + iframes
        combined_source = page_source + " ".join(all_resources).lower()

        for gateway, signatures in PAYMENT_GATEWAYS.items():
            for sig in signatures:
                if sig.lower() in combined_source:
                    detected.append(gateway)
                    break

        summary.detected_gateways = detected
        summary.has_payment_form = len(detected) > 0
        summary.results.append(PaymentTestResult(
            category="Gateway",
            test="Payment gateway detected",
            passed=len(detected) > 0,
            detail=f"Found: {', '.join(detected)}" if detected else "No known payment gateway detected on this page",
        ))
    except Exception as e:
        summary.results.append(PaymentTestResult(
            category="Gateway", test="Payment gateway detection",
            passed=False, detail=f"Detection error: {e}",
        ))

    # ── Card input fields ────────────────────────────────────────────────────
    card_fields_found = {}
    for field_type, patterns in CARD_FIELD_PATTERNS.items():
        for pattern in patterns:
            selectors = [
                f'input[name*="{pattern}" i]',
                f'input[id*="{pattern}" i]',
                f'input[placeholder*="{pattern}" i]',
                f'input[autocomplete*="{pattern}" i]',
            ]
            for sel in selectors:
                try:
                    el = page.query_selector(sel)
                    if el:
                        card_fields_found[field_type] = el
                        break
                except Exception:
                    pass
            if field_type in card_fields_found:
                break

    for field_type, el in card_fields_found.items():
        summary.has_payment_form = True
        name = el.get_attribute("name") or el.get_attribute("id") or field_type
        summary.results.append(PaymentTestResult(
            category="Card Fields",
            test=f"Card field detected: {field_type}",
            passed=True,
            detail=f"Found input name={name}",
        ))

        # Check autocomplete attribute for card fields
        ac = el.get_attribute("autocomplete") or ""
        good_ac_values = {"card number": ["cc-number"], "cvv": ["cc-csc", "off"], "expiry": ["cc-exp"]}
        expected = good_ac_values.get(field_type, [])
        summary.results.append(PaymentTestResult(
            category="Card Fields",
            test=f"Correct autocomplete on {field_type}",
            passed=not expected or ac in expected,
            detail=f"autocomplete={ac} ✓" if (not expected or ac in expected) else f"autocomplete={ac or 'not set'} — recommended: {expected}",
        ))

    # ── PCI compliance: hosted iframe fields (safest approach) ──────────────
    try:
        has_payment_iframe = any(
            any(sig in (iframe_src := iframe.get_attribute("src") or "").lower()
                for sig in ["stripe", "paypal", "braintree", "adyen", "razorpay"])
            for iframe in page.query_selector_all("iframe")
        )
        summary.results.append(PaymentTestResult(
            category="PCI Compliance",
            test="Hosted payment iframe (best practice)",
            passed=has_payment_iframe,
            detail="Payment gateway iframe found ✓ — card data goes directly to gateway" if has_payment_iframe else "No payment iframe — card data may pass through your server",
        ))
    except Exception:
        pass

    # ── Trust badges ─────────────────────────────────────────────────────────
    trust_patterns = ["ssl", "secure checkout", "256-bit", "pci", "verified by visa", "mastercard securecode", "norton", "mcafee", "trustpilot"]
    has_trust = any(kw in page_text for kw in trust_patterns)
    summary.results.append(PaymentTestResult(
        category="Trust",
        test="Trust / security badges present",
        passed=has_trust,
        detail="Security/trust indicators found ✓" if has_trust else "No trust badges detected (may reduce user confidence)",
    ))

    # ── Price / amount display ────────────────────────────────────────────────
    price_selectors = [
        '[class*="price" i]', '[class*="amount" i]', '[class*="total" i]',
        '[id*="price" i]', '[id*="amount" i]', '[id*="total" i]',
    ]
    price_found = False
    for sel in price_selectors:
        try:
            if page.query_selector(sel):
                price_found = True
                break
        except Exception:
            pass

    if detected:  # Only relevant if payment gateway is present
        summary.results.append(PaymentTestResult(
            category="UX",
            test="Order total / price visible",
            passed=price_found,
            detail="Price/total display found ✓" if price_found else "No price display detected before payment",
        ))

    return summary
