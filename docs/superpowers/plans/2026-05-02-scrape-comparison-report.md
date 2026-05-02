# Scrape Comparison Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a latest scrape comparison report before the next scrape updates consolidated state, then expose it in a frontend Changes tab.

**Architecture:** Add a focused Python service that compares previous consolidated records to the fresh scrape snapshot by `site` and `listing_id`/`property_number`. Wire it into the scrape stage before consolidation writes the updated snapshot. Load the generated JSON from the static frontend and render it in a sidebar-driven tab.

**Tech Stack:** Python standard library, existing scraper/consolidation services, vanilla HTML/CSS/JavaScript.

---

### Task 1: Backend Comparison Service

**Files:**
- Create: `src/japan_property_scraper/services/scrape_comparison.py`
- Test: `tests/test_scrape_comparison.py`

- [x] **Step 1: Write failing tests**

Run: `.venv/bin/python -m unittest tests/test_scrape_comparison.py -v`
Expected: FAIL because `scrape_comparison` does not exist.

- [ ] **Step 2: Implement comparison**

Build a pure function that returns `added`, `removed`, `price_changed`, and `other_changed` arrays plus summary counts.

- [ ] **Step 3: Verify tests pass**

Run: `.venv/bin/python -m unittest tests/test_scrape_comparison.py -v`
Expected: PASS.

### Task 2: Scrape Pipeline Wiring

**Files:**
- Modify: `src/japan_property_scraper/main.py`

- [ ] **Step 1: Write comparison report before consolidation**

During `_run_scrape_stage`, after all fresh listings are scraped and before `append_new_or_changed_listings`, load the previous consolidated snapshot and write `output/consolidated/latest_scrape_comparison.json`.

- [ ] **Step 2: Verify command help/imports**

Run: `.venv/bin/python -m compileall src tests`
Expected: PASS.

### Task 3: Frontend Changes Tab

**Files:**
- Modify: `frontend/listings_map/index.html`
- Modify: `frontend/listings_map/app.js`
- Modify: `frontend/listings_map/styles.css`
- Create: `api/latest-scrape-comparison.js`

- [ ] **Step 1: Add Map/Changes buttons in the left panel**

Keep the map as the default view. Add a Changes button that opens an unframed report panel.

- [ ] **Step 2: Load report JSON**

Try `/output/consolidated/latest_scrape_comparison.json`, `./data/latest_scrape_comparison.json`, then `/api/latest-scrape-comparison`.

- [ ] **Step 3: Render sections**

Show summary counts and tables for price changes, added, removed, and other changed properties.

- [ ] **Step 4: Verify static frontend syntax**

Run: `node --check api/latest-scrape-comparison.js`
Expected: PASS.
