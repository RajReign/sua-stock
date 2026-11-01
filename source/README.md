# Stock sheet source

These files build the weekly school stock sheets published from this repository. The weekly run uses
`refresh_all.py`, which builds and locks every school's sheet and replaces the school pages only if every
school succeeds. The passwords file is private, lives in Aman's Drive and is never committed here.

- `build_sheet.py`: one school's sheet from Zoho stock, open sales orders and open purchase orders, plus the
  Payments tab from that school's payments file.
- `payments.py`: each school's open invoices, credits and the How to pay details, from Xero only (D-100). The
  weekly run saves each Xero reply as `{"page_size": N, "response": <reply>}`; any doubt stops the whole run.
- `lock_sheet.py`: wraps a built sheet in its password screen.
- `unlock_sheet.py`: turns a published page back into its built sheet, for a fix that needs no new Zoho data.
- `template.html`, `logo-ink.svg`: the sheet's page and logo.
