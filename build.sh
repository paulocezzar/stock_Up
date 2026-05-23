#!/usr/bin/env bash
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
python manage.py bootstrap

# One-time wipe: only when RESET_STOCK is explicitly "true". Any other value
# (or unset) leaves existing stock data alone. After the wipe runs once on a
# deploy, unset / change the env var so future deploys don't keep clearing.
if [ "${RESET_STOCK}" = "true" ]; then
  python manage.py reset_stock_data --yes
fi

# import_ingredients is idempotent (keyed on NPD-I code) - safe to run on
# every deploy to keep the ingredient master + pack weights in sync.
python manage.py import_ingredients data/ingredients.xlsx

# import_packaging is the same shape (idempotent on NPD-P code). Packaging
# items land as Products in the "packaging" category and reuse the existing
# stocktake / delivery / reorder machinery; a RESET_STOCK wipe clears them
# alongside everything else because they're rows in the Product table.
python manage.py import_packaging data/packaging.xlsx

# import_customers reads the order-sheet workbook (Customers + WHOLESALE
# tabs) and is idempotent on name (case-insensitive). Render free tier
# has no shell, so running this on every deploy is how the live DB picks
# up new customers; manual type overrides are preserved via
# is_type_manual exactly like Recipe.is_sold_manual.
python manage.py import_customers data/order_sheet.xlsm

# import_recipes_bulk walks every sheet in the 93-recipe workbook and runs
# the per-sheet parser on each. Idempotent on NPD-R code, same as the
# single-recipe importer, so re-running on every deploy is safe.
# DELIBERATELY non-fatal: on Render free tier the web request itself can't
# parse 93 sheets within the 30s gunicorn worker timeout, so this is the
# canonical path for bulk recipe loads — but if a sheet here malforms or
# the file goes missing we want the deploy to continue (the rest of the
# app keeps working with the previous recipe data). Smaller single-recipe
# uploads still go through /recipes/upload/.
python manage.py import_recipes_bulk data/recipes_bulk_93.xlsx \
    || echo "import_recipes_bulk had errors; continuing deploy."

# import_sale_products reads the "Products" tab of the order-sheet
# workbook and creates / refreshes SaleProduct rows (the sellable SKUs —
# distinct from the ingredient Product model). Runs AFTER the recipe
# import so the auto-linker has recipes to match against on a first-
# ever deploy. Idempotent on name. Preserves manual recipe links and
# hand-created rows the same way import_customers does. Auto-links
# first by Sage No., then by exact name; ambiguous matches surface in
# the Products → Link review screen for the operator to confirm.
python manage.py import_sale_products data/order_sheet.xlsm

# import_orders walks customer tabs in the order-sheet workbook and
# loads each week's per-day product quantities. Chunk 2 only imports
# the GARDEN CAFE tab — once we've verified one customer end-to-end
# in the grid view we scale to the other tabs. Streams the workbook
# in read_only + data_only mode (same defensive pattern as the bulk
# recipe importer) and is idempotent on (customer, date): re-running
# replaces that customer's lines for the sheet's dates. DELIBERATELY
# non-fatal: a malformed tab or missing customer must not abort the
# deploy after the imports above have already run.
python manage.py import_orders data/order_sheet.xlsm \
        --tab "GARDEN CAFE" --tab "WHOLESALE" \
    || echo "import_orders had errors; continuing deploy."

# Historical order sheets in data/historical/ — one full week per file
# (e.g. order_sheet_2026_03_30.xlsm = w/c 30 Mar 2026). Each file is
# imported across ALL customer tabs, but ONLY ONCE: import_historical_orders
# skips a file whose week's Orders already exist, so a second deploy
# never re-does work or clobbers hand-edits. New historical files
# added to the folder land on the next deploy.
# DELIBERATELY non-fatal: a bad file/tab logs and the deploy continues.
if [ -d data/historical ]; then
  for f in data/historical/*.xlsm; do
    [ -e "$f" ] || continue  # no-match glob — empty folder, nothing to do
    python manage.py import_historical_orders "$f" \
        || echo "import_historical_orders $f had errors; continuing deploy."
  done
fi
