# Delhi Bus Journey Planner

Real bus travel times for Delhi, learned from the GPS of 6,000+ DTC buses (October 2026), with a journey planner
API and a map interface. A trip at 9 am on a weekday gets a different answer from the same trip at 11 pm.

Transport Stack Hackathon 2026, Problem 1: real-time bus traffic model and journey planner.

- **How it works:** [TECHNICAL_NOTE.md](TECHNICAL_NOTE.md)
- **How accurate it is:** [VALIDATION.md](VALIDATION.md)

## Quick start (data already processed)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd src && ../.venv/bin/uvicorn api:app --port 8000
```

Open **http://localhost:8000** for the map, or **http://localhost:8000/docs** for interactive API docs.

## API

### `GET /journeys`

| param | example | meaning |
|---|---|---|
| `from` | `ISBT Kashmere Gate`, `p12`, `28.667,77.229` | origin: place name, place id from `/places`, or `lat,lon` |
| `to` | `Nehru Place` | destination, same formats |
| `depart` | `2026-10-27T08:30` | local Delhi time. Only the day of the week and the time matter. Default: now |
| `options` | `3` | number of options (1–6) |

```bash
curl "http://localhost:8000/journeys?from=ISBT%20Kashmere%20Gate&to=Nehru%20Place&depart=2026-10-27T08:30"
```

Response (shortened):

```json
{
  "from": {"name": "ISBT Kashmere Gate", "lat": 28.667, "lon": 77.229},
  "to":   {"name": "Nehru Place", "lat": 28.548, "lon": 77.251},
  "day_type": "weekday",
  "options": [{
    "summary": "214DOWN → 425UP",
    "depart": "08:30", "arrive": "09:30", "total_min": 60.4,
    "walk_min": 6.2, "wait_min": 6.0, "in_bus_min": 48.2, "transfers": 1,
    "total_min_bad_day": 72.1, "total_min_timetable": 61.0,
    "quiet_hour": {"hour": "05:30", "total_min": 45.2},
    "by_hour": {"5": 45.2, "6": 47.0, "...": "..."},
    "legs": [
      {"type": "walk", "from": "ISBT Kashmere Gate", "to": "ISBT Bridge/ ISBT Nityanand Marg", "minutes": 3.1, "distance_m": 209},
      {"type": "bus", "route": "214DOWN", "board_stop": "ISBT Bridge/ ISBT Nityanand Marg", "alight_stop": "Darya Ganj",
       "board_time": "08:35", "alight_time": "08:46", "wait_minutes": 2.0, "ride_minutes": 12.0, "n_stops": 6,
       "data_quality": {"L1": 1.0, "L2": 0.0, "L3": 0.0, "L4": 0.0}, "stops": ["..."], "path": ["..."]},
      {"type": "bus", "route": "425UP", "...": "..."},
      {"type": "walk", "...": "..."}
    ]
  }]
}
```

- `total_min_bad_day`: the 85th-percentile time, i.e. a slow day.
- `total_min_timetable`: what the official schedule implies for the same buses.
- `quiet_hour` and `by_hour`: the same journey at every hour of the day, which shows the effect of traffic.
- `data_quality`: the share of the ride timed from direct GPS measurements (L1/L2) vs fallbacks (L3/L4).

### Other endpoints

- `GET /places`: every place (a group of same-name stops within 600 m) for dropdowns
- `GET /stops/search?q=nehru`: stop-name search
- `GET /traffic?day_type=weekday&hour=18`: modelled bus speed on every measured stretch, with road geometry
- `GET /health`

## Rebuilding everything from raw data

1. **GPS data** (16 GB): `bash download.sh` (resumable). It goes to `data/raw/`.
2. **Static GTFS**: download *Delhi Buses: GTFS Static Data* from
   [delhi.transportstack.in](https://delhi.transportstack.in) (free, needs an account) and unzip it into `data/gtfs/`.
3. Run the pipeline:

```bash
cd src
../.venv/bin/python prep_routes.py          # route geometry + timetable tables      (~15 s)
../.venv/bin/python process_all_days.py     # GPS → stop-to-stop times, all 31 days  (~2 h, ~5 GB disk at a time)
../.venv/bin/python build_model.py          # travel-time model → data/model/        (~2 min)
```

Each day is unpacked, processed and deleted in turn, so the 124 GB unpacked archive never has to fit on disk.
Peak memory is about 2 GB.

4. Validation (optional):

```bash
../.venv/bin/python build_model.py --train-until 2026-10-24 --out ../data/model_val
../.venv/bin/python validate.py --model ../data/model_val --test-from 2026-10-25
```

To add Google Maps figures, fill the `google_maps_total_min` column in `validation/google_maps_comparison.csv`
and re-run `validate.py`.

## Project layout

```
src/
  config.py            paths, holiday list
  geo.py               lat/lon ↔ metres
  prep_routes.py       stops placed along each route's road shape
  gps_process.py       one day of GPS → stop-to-stop observations
  process_all_days.py  runs gps_process for the whole month
  build_model.py       observations → travel-time model (4-level fallback)
  planner.py           RAPTOR journey search
  api.py               FastAPI server
  validate.py          validation report
web/index.html         map interface (Leaflet)
data/model/            the model (small, committed)
```

## Credits

Data: Delhi Transport Stack (DTC GPS, GTFS). Map: Leaflet, Esri basemap, © OpenStreetMap contributors.
Built with open-source Python libraries (DuckDB, pandas, SciPy, FastAPI) and with help from Claude (Anthropic),
an AI coding assistant, as allowed by the hackathon rules.
