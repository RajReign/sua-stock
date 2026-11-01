"""Payments tab data for each school, from Xero only (D-100). Zoho is never used for amounts owing.

Usage (check by hand): python3 source/payments.py <xero_invoices.json> <xero_credit_notes.json> <YYYY-MM-DD>

The weekly run reads Xero through the hosted connector (reads only, D-93) and saves each reply as
    {"page_size": <the pageSize it asked for>, "response": <the connector's reply, unchanged>}
list_invoices is called with statuses AUTHORISED; list_credit_notes with no filter. Both must come back
in one page: a reply holding page_size records or more may have more pages, so it is refused.

Rules:
- An invoice is shown only if it is a sales invoice (ACCREC), AUTHORISED, has amount due above zero and its
  contact name is exactly one of the school names. Paid, draft and voided invoices, supplier bills and
  sales invoices to anyone else (for example Work In Style) never appear.
- Credits already taken off an invoice are named from the credit notes' allocations to that invoice; they
  must add up to Xero's amount credited, or nothing is published.
- Unused credit is a sales credit note (ACCRECCREDIT), AUTHORISED, with remaining credit above zero.
- Status is counted in whole days from the as-at date (the Sydney date of the run) to the due date.
Any missing, malformed or doubtful figure stops the whole run: no school is published (T-STK-09).
"""
import json, sys
from datetime import date
from decimal import Decimal

DUE_SOON_DAYS = 7
PAY_TO = {                                   # one place for the How to pay box (T-STK-12)
    "name": "School Uniforms Australia Pty Ltd",
    "bank": "Commonwealth Bank",
    "bsb": "067 873",
    "account": "25091619",
    "reference": "Please use the invoice number as the payment reference.",
}


def fail(msg):
    raise SystemExit(f"Xero payments: {msg}; nothing published")


def load(path, key):
    try:
        wrapped = json.load(open(path))
    except (OSError, ValueError) as e:
        fail(f"cannot read {path} ({e})")
    if not isinstance(wrapped, dict) or "page_size" not in wrapped or "response" not in wrapped:
        fail(f"{path} is not in the saved form {{page_size, response}}")
    resp = wrapped["response"]
    data = resp.get("data", resp) if isinstance(resp, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        fail(f"{path} has no {key} list; the Xero read may have failed")
    rows = data[key]
    if len(rows) >= int(wrapped["page_size"]):
        fail(f"{path} returned a full page of {len(rows)}; there may be more pages")
    return rows


def money(v, what):
    if v is None:
        fail(f"{what} has no amount")
    try:
        return Decimal(str(v))
    except Exception:
        fail(f"{what} has an amount that is not a number ({v!r})")


def day(v, what):
    try:
        return date.fromisoformat(str(v)[:10])
    except Exception:
        fail(f"{what} has no valid date ({v!r})")


def status(due, as_at):
    n = (due - as_at).days
    if n < 0:
        return "overdue", f"Overdue by {-n} day{'s' if n != -1 else ''}"
    if n == 0:
        return "soon", "Due today"
    return ("soon" if n <= DUE_SOON_DAYS else "later"), f"Due in {n} day{'s' if n != 1 else ''}"


def school_payments(invoices_path, credits_path, schools, as_at_text):
    """schools: list of (code, exact Xero contact name). Returns {code: payments dict}."""
    as_at = date.fromisoformat(as_at_text)
    invoices = load(invoices_path, "_Invoices")
    credits = load(credits_path, "_CreditNotes")
    by_name = {name: code for code, name in schools}
    applied = {}                                   # invoice number -> [(date, credit note number, amount)]
    unused = {code: [] for code, _ in schools}
    for c in credits:
        if c.get("type") != "ACCRECCREDIT":
            continue
        num = c.get("creditNoteNumber") or "(no number)"
        for a in c.get("allocations") or []:
            inv = (a.get("invoice") or {}).get("invoiceNumber")
            if inv:
                applied.setdefault(inv, []).append((str(a.get("date", ""))[:10], num, money(a.get("amount"), f"credit note {num}")))
        code = by_name.get((c.get("contact") or {}).get("name"))
        if code and c.get("status") == "AUTHORISED" and money(c.get("remainingCredit"), f"credit note {num}") > 0:
            unused[code].append({"number": num, "date": str(day(c.get("date"), f"credit note {num}")),
                                 "reference": c.get("reference") or "",
                                 "remaining": float(money(c.get("remainingCredit"), f"credit note {num}"))})
    out = {code: {"as_at": as_at_text, "invoices": [], "credits": unused[code], "pay_to": PAY_TO} for code, _ in schools}
    for i in invoices:
        code = by_name.get((i.get("contact") or {}).get("name"))
        if not code or i.get("type") != "ACCREC" or i.get("status") != "AUTHORISED":
            continue
        num = i.get("invoiceNumber")
        if not num:
            fail(f"a {code} invoice has no number")
        due_amt = money(i.get("amountDue"), f"invoice {num}")
        if due_amt <= 0:
            continue
        total = money(i.get("total"), f"invoice {num}")
        credited = money(i.get("amountCredited") or 0, f"invoice {num}")
        paid = money(i.get("amountPaid") or 0, f"invoice {num}")
        if total - credited - paid != due_amt:
            fail(f"invoice {num}: total {total} less credited {credited} and paid {paid} is not the amount due {due_amt}")
        cns = sorted(applied.get(num, []))
        if credited > 0 and sum(a for _, _, a in cns) != credited:
            fail(f"invoice {num}: credit notes allocated ({sum(a for _, _, a in cns)}) do not match the amount credited {credited}")
        due = day(i.get("dueDate"), f"invoice {num}")
        band, text = status(due, as_at)
        out[code]["invoices"].append({
            "number": num, "issued": str(day(i.get("date"), f"invoice {num}")), "due": str(due),
            "total": float(total), "credited": float(credited), "paid": float(paid), "amount_due": float(due_amt),
            "credit_notes": [n for _, n, _ in cns], "band": band, "status": text,
        })
    for p in out.values():
        p["invoices"].sort(key=lambda r: (r["due"], r["number"]))
        tot = {"overdue": Decimal(0), "soon": Decimal(0), "later": Decimal(0)}
        for r in p["invoices"]:
            tot[r["band"]] += Decimal(str(r["amount_due"]))
        p["totals"] = {k: float(v) for k, v in tot.items()}
        p["total_owing"] = float(sum(tot.values()))
        p["next_due"] = next((r["due"] for r in p["invoices"] if r["band"] != "overdue"), None)
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) != 3:
        raise SystemExit(__doc__)
    from refresh_all import SCHOOLS
    print(json.dumps(school_payments(a[0], a[1], SCHOOLS, a[2]), indent=1))
