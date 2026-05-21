# Bakery Stock — personal stock & supplier price tool

Replaces the Price_Comparison + Stocktake spreadsheets with a single Django app.
Products, suppliers and prices are relational, so "cheapest supplier" is a live
query (no more #REF! errors), and a stocktake is a record in the DB, not a dated
file copy.

## Run locally
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py createsuperuser
    python manage.py import_data --stocktake Stocktake_18_05_2026.xlsx --prices Price_Comparison.xlsx
    python manage.py runserver
- `/`        dashboard (cheapest supplier, on-hand, reorder flags, stock value)
- `/count/`  tap-through stocktake screen (saves each line as you type)
- `/admin/`  add/edit products, suppliers and prices

## Deploy to Render (free)
1. Push this folder to a GitHub repo.
2. Render dashboard -> New -> Blueprint -> pick the repo. `render.yaml` provisions
   the web service + free Postgres automatically.
3. After first deploy, open the Render shell and run:
       python manage.py createsuperuser
       python manage.py import_data --stocktake <path> --prices <path>
   (or upload via /admin/). The free web service sleeps after 15 min idle;
   first request after that takes ~30-60s.

## Data model
Supplier --< SupplierPrice >-- Product --< StockLine >-- Stocktake
`needed` and stock `value` are computed at read time, never stored.
