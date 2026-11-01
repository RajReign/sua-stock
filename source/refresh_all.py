"""Weekly refresh: build and lock every school's stock sheet, and write them into the site only if all succeed.

Usage: python3 source/refresh_all.py <zoho_items.json> <open.json> <keys.json> <YYYY-MM-DD> <site_dir> <summary.json>
       <xero_invoices.json> <xero_credit_notes.json> [recount.json]

Run from anywhere; site_dir is the root of the sua-stock repository. Every school in SCHOOLS is built with
build_sheet.py and locked with lock_sheet.py into a temporary folder first. If any school fails (no items,
a missing stock figure, an open order line with an unknown SKU, no password entry, a template placeholder
left unfilled, a recount SKU that is not an active item of any school, or any doubt in the Xero payments reads, see payments.py), nothing in site_dir is touched and the script exits with an error naming the school.
Only when all succeed are the school folders copied over their old pages. CNAME, robots.txt, index.html
and the source folder are never touched. keys.json must never be written into site_dir.
recount.json (optional): {"skus": [...]}, sizes waiting for a shelf count; each school's sheet shows them as not
available and its summary lists them with the true Zoho figure (see build_sheet.py).
"""
import json, os, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from payments import school_payments

HERE = os.path.dirname(os.path.abspath(__file__))
SCHOOLS = [                      # code, name as shown on the sheet
    ("GPS", "Glenhaven Public School"),
    ("JPPS", "John Purchase Public School"),
    ("MFPS", "Murray Farm Public School"),
    ("MPPS", "Matthew Pearce Public School"),
    ("ODPS", "Oakhill Drive Public School"),
]
KEEP = {"CNAME", "robots.txt", "index.html", "source", ".git"}


def run(args):
    r = subprocess.run([sys.executable] + args, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit((r.stderr or r.stdout).strip() or f"failed: {args}")
    return r.stdout


def main(items, open_path, keys_path, as_at, site, summary_path, xero_invoices, xero_credits, recount_path=""):
    keys = json.load(open(keys_path))
    if os.path.abspath(keys_path).startswith(os.path.abspath(site) + os.sep):
        raise SystemExit("the passwords file is inside the site folder; move it out before publishing")
    missing = [c for c, _ in SCHOOLS if c not in keys or not keys[c].get("password") or not keys[c].get("path")]
    if missing:
        raise SystemExit(f"no password entry for {', '.join(missing)}; nothing published")
    pays = school_payments(xero_invoices, xero_credits, SCHOOLS, as_at)   # stops the run on any doubt
    tmp = tempfile.mkdtemp()
    summaries, log = [], []
    all_items = json.load(open(items)); all_items = all_items.get("data", all_items)["items"]
    all_open = json.load(open(open_path))
    every = {i["sku"] for i in all_items if i.get("status") == "active" and i["name"].upper().split()[0] in {c for c, _ in SCHOOLS}}
    for o in all_open["orders"]:
        for l in o["lines"]:
            if l["sku"] not in every:
                raise SystemExit(f'open order {o["number"]} has SKU {l["sku"]}, which is not an active item of any school; nothing published')
    recount = json.load(open(recount_path))["skus"] if recount_path else []
    unknown = [k for k in recount if k not in every]
    if unknown:
        raise SystemExit(f"recount list has {len(unknown)} SKUs that are not active items of any school (first: {unknown[0]}); nothing published")
    for code, name in SCHOOLS:
        built = os.path.join(tmp, f"{code}.html")
        summ = os.path.join(tmp, f"{code}.json")
        skus = {i["sku"] for i in all_items if i["name"].upper().split()[0] == code and i.get("status") == "active"}
        mine = dict(all_open)
        mine["orders"] = [dict(o, lines=[l for l in o["lines"] if l["sku"] in skus]) for o in all_open["orders"]]
        mine["orders"] = [o for o in mine["orders"] if o["lines"]]
        school_open = os.path.join(tmp, f"{code}.open.json")
        json.dump(mine, open(school_open, "w"))
        school_pay = os.path.join(tmp, f"{code}.payments.json")
        json.dump(pays[code], open(school_pay, "w"))
        log.append(run([os.path.join(HERE, "build_sheet.py"), items, code, name, as_at, built, school_open, summ, school_pay, recount_path]))
        log.append(run([os.path.join(HERE, "lock_sheet.py"), built, keys_path, code, os.path.join(tmp, "site")]))
        s = json.load(open(summ))
        s["owing"] = {"total": pays[code]["total_owing"], "invoices": len(pays[code]["invoices"]), **pays[code]["totals"]}
        s["link"] = f"https://stock.schooluniformsaustralia.com.au/{keys[code]['path']}/"
        summaries.append(s)
    for code, _ in SCHOOLS:                                   # all built and locked: now replace the pages
        folder = keys[code]["path"]
        if folder in KEEP:
            raise SystemExit(f"{code}: link code {folder} would overwrite a protected file")
        dst = os.path.join(site, folder)
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(os.path.join(tmp, "site", folder), dst)
    json.dump({"as_at": as_at, "schools": summaries}, open(summary_path, "w"), indent=1, ensure_ascii=False)
    print("".join(log))
    for s in summaries:
        print(f"{s['school_code']}: {s['garments']} garments, {s['sizes_in_stock']} of {s['sizes']} sizes in stock, "
              f"{s['units']} units, {len(s['sizes_at_zero'])} sizes at zero, {len(s['over_free_hold'])} styles over 150, "
              f"owing ${s['owing']['total']:,.2f} on {s['owing']['invoices']} invoices (overdue ${s['owing']['overdue']:,.2f})")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) not in (8, 9):
        raise SystemExit(__doc__)
    main(*a)
