"""Build one school's weekly stock sheet from a Zoho Inventory items export.

Usage: python3 build_sheet.py <zoho_items.json> <SCHOOL_CODE> "<School name>" <YYYY-MM-DD> <out.html> [open.json] [summary.json] [payments.json] [recount.json]

Prices: Zoho holds selling rates ex GST; the sheet shows rate x 1.1, rounded to the cent, per size (D-90).
Stock: physical stock on hand for each active item whose name starts with the school code, given in the
  items file as stock_on_hand (the run reads it by the route sys-zoho-inventory names).
open.json (optional): {"orders": [{"number", "date", "lines": [{"sku", "qty"}]}],   open sales orders (D-89)
                       "incoming": {"<sku>": qty}, "incoming_when": "<text>"}         open purchase orders
summary.json (optional): written for the weekly run: counts, sizes at zero, styles over the 150 free limit.
payments.json (optional): this school's Payments tab, made by payments.py from Xero only (D-100). Without it
  the sheet has no Payments tab; the weekly run always passes it.
recount.json (optional): {"skus": ["<sku>", ...]}, sizes waiting for a shelf count. Each is shown as not available
  (stock 0, so it cannot be ordered) until counted; the summary lists them under "recount" with the true Zoho figure.
template.html and logo-ink.svg are read from the folder this script is in.
"""
import json, os, re, sys, base64
from decimal import Decimal, ROUND_HALF_UP

HERE = os.path.dirname(os.path.abspath(__file__))
FREE_HOLD = 150                                 # units per style held free (current terms; template shows the same)
ORDER_EMAIL = "aman@schooluniformsaustralia.com.au"
TERMS = ("Order quantities should be in multiples of 25 per style. "
         "SUA holds up to 150 units per style free of charge in our warehouse on your behalf. "
         "Prices include GST.")
SECTION_ORDER = ["Girls", "Boys", "Sport", "Unisex and accessories"]
SIZE_WORDS = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL"]
ONE_SIZE = {"00", "ST", "SM", "LG"}          # ties: one size per item code
SIZE_RE = re.compile(r"^(?P<base>.+?)-(?P<size>\d{2}-\d{2}|\d{2}|XXS|XS|S|M|L|XL|XXL|3XL|SM|LG|ST)$")
SMALL = {"with", "and", "on", "of"}
KEEP_UPPER = {"SS", "LS", "S/S", "L/S"}


def section_for(name):
    """Girls, Boys, Sport, then Unisex and accessories."""
    n = name.upper()
    if "SPORT" in n:
        return "Sport"
    if "BOYS" in n or "BOY'S" in n:
        return "Boys"
    if any(w in n for w in ("GIRLS", "GIRL'S", "BLOUSE", "DRESS", "TUNIC", "CULOTTE", "CULLOTTE")):
        return "Girls"
    return "Unisex and accessories"


def type_rank(name):
    """Order within a group: tops, dresses, bottoms, outerwear, ties."""
    n = name.upper()
    for rank, words in enumerate([("SHIRT", "BLOUSE", "POLO"), ("DRESS", "TUNIC", "CULOTTE", "CULLOTTE"),
                                  ("SHORTS", "PANTS", "TROUSER", "SKIRT"), ("JACKET", "JUMPER", "VEST", "FLEECY"),
                                  ("TIE",)]):
        if any(w in n for w in words):
            return rank
    return 9


def size_key(size):
    s = size.upper()
    m = re.match(r"^(\d{2})(?:-\d{2})?$", s)
    if m:
        return (0, int(m.group(1)), "")
    if s in SIZE_WORDS:
        return (1, SIZE_WORDS.index(s), "")
    return (2, 0, s)


def word_case(w):
    if w.upper() in KEEP_UPPER:
        return w.upper()
    if w.lower() in SMALL:
        return w.lower()
    if "/" in w:
        return "/".join(p.capitalize() for p in w.split("/"))
    if w.startswith("("):
        return "(" + w[1:].capitalize()
    return w.capitalize()


def tidy(name, code):
    n = re.sub(r"\s*\([^)]*\)\s*$", "", name)                    # drop trailing "(SKU)"
    n = re.sub(r"^" + re.escape(code) + r"\s*-?\s*", "", n, flags=re.I)  # drop "GPS - ", "JPPS -", "MPPS "
    n = re.sub(r"\s+", " ", n).strip(" -")
    words = n.split()
    out = [word_case(w) for w in words]
    if out:
        out[0] = out[0][0].upper() + out[0][1:]
    return " ".join(out)


def split_sku(sku):
    m = SIZE_RE.match(sku)
    if m:
        return m.group("base"), m.group("size")
    base, _, size = sku.rpartition("-")
    return base, size


def style_code(base):
    m = re.match(r"^([A-Z]-?\d{4})", base)
    return m.group(1).replace("-", "") if m else base


def price_inc(rate):
    return float((Decimal(str(rate)) * Decimal("1.1")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build(items_path, code, school, as_at, out_path, open_path=None, summary_path=None, payments_path=None, recount_path=None):
    recount = set(json.load(open(recount_path))["skus"]) if recount_path else set()
    opn = json.load(open(open_path)) if open_path else {"orders": [], "incoming": {}, "incoming_when": ""}
    open_qty = {}
    for o in opn["orders"]:
        for l in o["lines"]:
            open_qty[l["sku"]] = open_qty.get(l["sku"], 0) + l["qty"]
    raw = json.load(open(items_path))
    data = raw.get("data", raw)
    items = [i for i in data["items"]
             if re.match(re.escape(code) + r"\b", i["name"].upper()) and i.get("status") == "active"]
    if not items:
        raise SystemExit(f"{code}: no active items found; the items file may be incomplete")
    missing = [i["sku"] for i in items if i.get("stock_on_hand") is None]
    if missing:
        raise SystemExit(f"{code}: no stock figure for {len(missing)} items (first: {missing[0]}); nothing built")
    recount &= {i["sku"] for i in items}                    # refresh_all.py has already refused unknown SKUs
    garments = {}
    for i in items:
        sku = i["sku"]
        base, size = split_sku(sku)
        g = garments.setdefault(base, {"name": None, "code": style_code(base), "sizes": []})
        nm = tidy(i["name"], code)
        if g["name"] is None or len(nm) > len(g["name"]):   # keep the fullest spelling of the name
            g["name"] = nm
        label = "One size" if size.upper() in ONE_SIZE else size
        on_hand = int(round(i["stock_on_hand"]))
        ordered = open_qty.get(sku, 0)
        short = max(0, ordered - on_hand)                    # open orders draw on shelf stock first
        g["sizes"].append({"size": label, "sku": sku, "price": price_inc(i["rate"]),
                           "on_hand": on_hand, "stock": 0 if sku in recount else max(0, on_hand - ordered),
                           "incoming_spare": max(0, opn["incoming"].get(sku, 0) - short)})
    names = {}
    for g in garments.values():
        names.setdefault(g["name"], []).append(g)
    sections = {}
    for base, g in garments.items():
        g["sizes"].sort(key=lambda s: size_key(s["size"]))
        prices = [s["price"] for s in g["sizes"]]
        g["price"] = min(prices)
        g["price_varies"] = len(set(prices)) > 1
        sections.setdefault(section_for(g["name"]), []).append(g)
    sheet = {
        "school": school,
        "school_code": code,
        "as_at": as_at,
        "order_email": ORDER_EMAIL,
        "terms": TERMS,
        "sections": [{"name": s, "garments": sorted(sections[s], key=lambda g: (type_rank(g["name"]), g["name"], g["code"]))}
                     for s in SECTION_ORDER if s in sections],
        "open_orders": [],
        "on_order": [],
        "payments": None,
    }
    if payments_path:
        pay = json.load(open(payments_path))
        if pay.get("as_at") != as_at:
            raise SystemExit(f"{code}: payments file is for {pay.get('as_at')}, not {as_at}")
        sheet["payments"] = pay
    by_sku = {s_["sku"]: (g, s_) for g in garments.values() for s_ in g["sizes"]}
    left = {k: v["on_hand"] for k, (g_, v) in by_sku.items()}
    for o in opn["orders"]:
        lines = []
        for l in o["lines"]:
            if l["sku"] not in by_sku:
                raise SystemExit(f'{code}: open order {o["number"]} has SKU {l["sku"]}, which is not an active {code} item')
            g_, s_ = by_sku[l["sku"]]
            from_shelf = min(l["qty"], left[l["sku"]])
            left[l["sku"]] -= from_shelf
            status = ("Ready to deliver" if from_shelf == l["qty"] else
                      "Arriving with the next shipment" if from_shelf == 0 else
                      f"{from_shelf} ready, {l['qty'] - from_shelf} arriving with the next shipment")
            lines.append({"name": f'{g_["name"]} ({g_["code"]})', "size": s_["size"], "qty": l["qty"], "status": status})
        sheet["open_orders"].append({"number": o["number"], "date": o["date"], "lines": lines})
    for g in garments.values():
        spare = [{"size": s_["size"], "qty": s_["incoming_spare"]} for s_ in g["sizes"] if s_["incoming_spare"] > 0]
        if spare:
            sheet["on_order"].append({"name": f'{g["name"]} ({g["code"]})', "expected": opn["incoming_when"], "sizes": spare})
    logo = open(os.path.join(HERE, "logo-ink.svg"), "rb").read()
    logo_uri = "data:image/svg+xml;base64," + base64.b64encode(logo).decode()
    html = open(os.path.join(HERE, "template.html")).read()
    html = html.replace("__TITLE__", f"{school} weekly stock").replace("__LOGO__", logo_uri)
    html = html.replace("__DATA__", json.dumps(sheet, ensure_ascii=False))
    if "__DATA__" in html or "__TITLE__" in html or "__LOGO__" in html:
        raise SystemExit(f"{code}: a template placeholder was not filled")
    open(out_path, "w").write(html)
    n_sizes = sum(len(g["sizes"]) for g in garments.values())
    n_stock = sum(1 for g in garments.values() for s in g["sizes"] if s["stock"] > 0)
    units = sum(s["stock"] for g in garments.values() for s in g["sizes"])
    zero = [{"sku": s_["sku"], "garment": f'{g["name"]} ({g["code"]})', "size": s_["size"],
             "on_hand": s_["on_hand"], "open_orders": open_qty.get(s_["sku"], 0)}
            for g in garments.values() for s_ in g["sizes"] if s_["stock"] == 0 and s_["sku"] not in recount]
    held = [{"sku": s_["sku"], "garment": f'{g["name"]} ({g["code"]})', "size": s_["size"],
             "zoho_on_hand": s_["on_hand"], "open_orders": open_qty.get(s_["sku"], 0)}
            for g in garments.values() for s_ in g["sizes"] if s_["sku"] in recount]
    over = []
    for g in garments.values():
        total = sum(s_["stock"] for s_ in g["sizes"])       # the same total the sheet's storage bar shows
        if total > FREE_HOLD:
            over.append({"garment": f'{g["name"]} ({g["code"]})', "units": total, "over": total - FREE_HOLD})
    summary = {"school_code": code, "school": school, "as_at": as_at, "items": len(items), "garments": len(garments),
               "sizes": n_sizes, "sizes_in_stock": n_stock, "units": units, "sizes_at_zero": zero,
               "recount": held,
               "over_free_hold": sorted(over, key=lambda r: -r["over"])}
    if summary_path:
        json.dump(summary, open(summary_path, "w"), indent=1, ensure_ascii=False)
    print(f"{school}: {len(items)} items, {len(garments)} garments, {n_sizes} sizes, {n_stock} in stock, {units} units")
    for sec in sheet["sections"]:
        for g in sec["garments"]:
            print(f"   {sec['name']:<17} {g['code']:<6} {g['name']:<42} {'from ' if g['price_varies'] else ''}${g['price']:.2f}  "
                  + " ".join(f"{s['size']}:{s['stock']}" for s in g["sizes"]))


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 5:
        raise SystemExit(__doc__)
    build(a[0], a[1], a[2], a[3], a[4], a[5] if len(a) > 5 and a[5] else None, a[6] if len(a) > 6 and a[6] else None,
          a[7] if len(a) > 7 and a[7] else None, a[8] if len(a) > 8 and a[8] else None)
