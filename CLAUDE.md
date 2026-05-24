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
---

<!-- Karpathy behavioural guidelines, from https://raw.githubusercontent.com/forrestchang/andrej-karpathy-skills/main/CLAUDE.md -->
# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

