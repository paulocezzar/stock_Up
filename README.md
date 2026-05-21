# Stock Ops — bakery stock & supplier price tool

A small Django app that replaces the price-comparison + stocktake spreadsheets.
Everything is relational, so "cheapest supplier" is a live query (no #REF! rot),
and each weekly stocktake is kept as history.

You add your own data in the app:
1. Suppliers  → add your suppliers
2. Ingredients → add each ingredient (code, name, unit, minimum/par level)
3. Open an ingredient → add its pack prices per supplier (cheapest is auto-flagged)
4. Stocktakes → "Start count for today", type what's on hand; it saves as you go
5. Dashboard → cheapest supplier, value, and what's below minimum (reorder list)

## Run locally
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py createsuperuser
    python manage.py runserver
Visit http://127.0.0.1:8000/

## Deploy to Render (free)
Push to GitHub, then Render -> New -> Blueprint -> pick the repo.
`render.yaml` provisions the web service + free Postgres.
Set env vars ADMIN_USER / ADMIN_PASS / ADMIN_EMAIL so `build.sh` can create your
login automatically (Render free has no shell). The DB starts empty — add data in-app.

Note: the free web service sleeps after ~15 min idle (first hit ~30-60s).


## Multi-user & departments
- Everything sits behind a login (`/login/`). The owner is the superuser created on deploy.
- A **Department** (Bakery, Butchery, ...) owns its own ingredients and stocktakes.
  Suppliers are shared across all departments.
- Add departments and users in Django **/admin/**: open a Department and tick its
  members; each user only sees the departments they belong to.
- Use the department switcher (top-right) to move between units you can access.
- Delete buttons exist for suppliers, ingredients, and prices.
- On first deploy a starter department "Bakery" is created with the owner in it.
