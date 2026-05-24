# STOCK.UP — Claude Code project rules

## Command execution
- Run commands in the FOREGROUND and read their output directly.
- NEVER use polling/wait loops (no `until ... do sleep`, no `tail -f` waits, no background log-file polling) — they hang forever if the expected text never appears.
- Run the test suite directly (`python manage.py test`); it takes ~1-2 min. Use a real timeout if needed, never a sleep loop.
- End each completed task with: powershell -c "[console]::beep(800,400); [console]::beep(1000,400)"
- Commits: no Co-Authored-By trailer.

## Deploy & environment
- Single channel: all changes go through Claude Code. Push to `main` auto-deploys to Render.
- Render free-tier: 512MB RAM, ~30s worker timeout, NO shell. Bulk imports MUST use `load_workbook(read_only=True, data_only=True)` + `iter_rows(values_only=True)` and run in build.sh — never as a web upload (causes OOM/timeout).
- Render phantom-failure: a vague "no open ports detected" during rapid deploys is usually false if gunicorn is serving — fix with dashboard "Manual Deploy → Deploy latest commit"; space out pushes.
- `.xlsx/.xlsm` files are gitignored — data files need `git add -f`.
- Always run the FULL test suite before committing; all tests must pass.

## Data model (critical conventions — do not break)
- `Product` = INGREDIENTS. `SaleProduct` = sellable goods. NEVER overload `Product`.
- Order/customer totals are ALWAYS computed from DAILY ordered cells × price (Mon–Sun). NEVER read the sheet's weekly "Total"/"Total ££" columns — they are formula cells, often blank/wrong.
- OrderLine SNAPSHOTS product_name + unit_price (financial records, immune to catalogue/price changes). sale_product link is optional/convenience only.
- Blank prices on order tabs are filled: tab cell → that week's Products tab → data/reference_prices.csv (2 Mar prices) → £0. Sheet/reference-authoritative; NEVER use the live SaleProduct catalogue for historical lines.
- Week-commencing (Monday) is always DERIVED from the order date, never stored.
- Historical imports are version-gated (HISTORICAL_IMPORT_VERSION); bump it to force re-import of existing weeks after an import-logic fix.

## Code style & process
- Prefer smaller, well-structured files following best-practice principles.
- Build in small, verifiable chunks; reconcile financial imports against the source rather than trusting the rendered page.
- Theme: dark industrial + amber (Space Grotesk / DM Mono), light-mode toggle.