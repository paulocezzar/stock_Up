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
