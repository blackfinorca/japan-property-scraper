# Japan Property Scraper

Python web scraping app for Japanese real estate listings.

## Run scripts

Default pipeline (scrape only):

```bash
.venv/bin/python run.py
```

Run selected pipeline stages with `--tags`:

```bash
# scrape + OpenAI eligibility + ryokan summary
.venv/bin/python run.py --tags scrape,openai,summary

# geocode backend cache + export map payload JSON
.venv/bin/python run.py --tags geocode

# export map payload JSON from cache only
.venv/bin/python run.py --tags map-export

# OpenAI only (all unique consolidated records)
.venv/bin/python run.py --tags openai

# OpenAI only for selected properties
.venv/bin/python run.py --tags openai \
  --property-number 70049 \
  --property-number 69199 \
  --property-number 69071 \
  --property-number 70039 \
  --property-number 70023

# Summary XLS only
.venv/bin/python run.py --tags summary
```

Legacy direct entry points are still available:

```bash
.venv/bin/python run_ryokan_licence_eligibility.py
.venv/bin/python ryokan-summary.py
```

## Listings Map Frontend (Google Maps)

Separate frontend app:

- `frontend/listings_map/index.html`
- `frontend/listings_map/app.js`
- `frontend/listings_map/styles.css`

Run from project root:

```bash
python3 -m http.server 8000
```

Preferred (safer) key setup: local git-ignored file

Create `frontend/listings_map/config.local.json`:

```json
{
  "mapsApiKey": "YOUR_GOOGLE_MAPS_API_KEY"
}
```

Then open:

```text
http://localhost:8000/frontend/listings_map/index.html
```

Build backend map payload first:

```bash
.venv/bin/python run.py --tags geocode
```

Note:
- Backend geocoding requires `Geocoding API` enabled for the key/project.
- Recommended server env var:
  - `GOOGLE_GEOCODING_API_KEY=<your_key>`

Alternative: pass key in URL:

```text
http://localhost:8000/frontend/listings_map/index.html?mapsApiKey=YOUR_GOOGLE_MAPS_API_KEY
```

Optional custom data path:

```text
http://localhost:8000/frontend/listings_map/index.html?mapsApiKey=YOUR_GOOGLE_MAPS_API_KEY&data=/output/consolidated/listings_map_payload.json
```

If Google shows "This page didn't load Google Maps correctly":

1. Ensure Google Cloud billing is enabled for the project.
2. Enable both APIs:
   - Maps JavaScript API
   - Geocoding API
3. Add HTTP referrer restriction for local dev (example):
   - `http://localhost:8000/*`
4. Clear cached key once:
   - `http://localhost:8000/frontend/listings_map/index.html?resetMapsKey=1&mapsApiKey=YOUR_GOOGLE_MAPS_API_KEY`

Standalone map payload command:

```bash
.venv/bin/python run_map_payload.py --help
```




## App Description

- Dedicated scraper function pattern for each real estate site (currently
  implemented for Hachise).
- Each run scrapes listings and saves site-level output as:
  - structured JSON file with timestamp
  - XLSX file with timestamp
- App consolidates all listings into central JSON and CSV files.
- After each run, only **new or changed listings** are appended to consolidated
  files to keep change history.
- Code is organized with PEP 8-friendly structure and naming.

## Project Structure

```text
japan-property-scraper/
├── .gitignore
├── README.md
├── requirements.txt
├── run.py
├── output/
│   ├── consolidated/
│   └── raw/
└── src/
    └── japan_property_scraper/
        ├── __init__.py
        ├── config.py
        ├── main.py
        ├── services/
        │   ├── __init__.py
        │   ├── consolidation.py
        │   └── exporters.py
        └── sites/
            ├── __init__.py
            ├── _hachise_constants.py
            ├── _hachise_detail_parser.py
            ├── hachise.py
```

## Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## Run the App

```bash
python run.py
```

## Output Files

### Per-site timestamped files

- `output/raw/<site_name>_<YYYYMMDD_HHMMSS>.json`
- `output/raw/<site_name>_<YYYYMMDD_HHMMSS>.xlsx`

### Central consolidated files

- `output/consolidated/consolidated_changes.json`
- `output/consolidated/consolidated_changes.csv`

These consolidated files receive only records classified as:

- `new`: listing not seen before
- `changed`: listing exists but tracked fields have changed

## Scraper Contract for Each Site Function

Hachise scraper currently returns:

- `property_number`
- `property_name`
- `location`
- `address`
- `land_area`
- `floor_area`
- `reno_status` (`renovated`, `nonrenovated`, `others`)
- `type` (`kyo_machiya` and normalized variants)
- `price_jpy`
- `price_usd`
- `status`
- `time_stamp`
- `summary` (empty string for now)
- `transportations` (list)
- `private_street_area_included`
- `building_structure`
- `building_date`
- `adjoining_street` (list)
- `public_utility`
- `land_use_district`
- `legal_restrictions`
- `handover`
- `current_situation`
- `building_coverage_ratio`
- `floor_area_ratio`
- `land_category`
- `geographical_features`
- `land_tenure`
- `notification_according_to_national_land_utilization_law`
- `elementary_school`
- `junior_high_school`
- `city_planning_act`
- `remarks` (list)
- `transaction_terms`
- `sales_representative`
- `information_updated`
- `information_will_be_updated`

For consolidation/change tracking, each record also carries:

- `site`
- `listing_id`
- `title`
- `url`

Example listing dictionary:

```python
{
    "property_number": "70062",
    "property_name": "Takase River–View Machiya 3 Min to Kiyomizu-Gojo",
    "location": "Shimogyo Ward",
    "address": "Nishihashidumecho, Shimogyo Ward",
    "land_area": "63.70 sqm",
    "floor_area": "90.53 sqm",
    "reno_status": "renovated",
    "type": "kyo_machiya",
    "price_jpy": 198000000,
    "price_usd": 1287000,
    "status": "Feb 27, New Property",
    "time_stamp": "2026-02-27T20:00:00",
    "summary": "",
    "site": "hachise",
    "listing_id": "70062",
    "title": "Takase River–View Machiya 3 Min to Kiyomizu-Gojo",
    "url": "https://www.hachise.com/buy/70062/index.html"
}
```

## Notes

- Implemented scraper:
  - `src/japan_property_scraper/sites/hachise.py`
