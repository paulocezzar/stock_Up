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
