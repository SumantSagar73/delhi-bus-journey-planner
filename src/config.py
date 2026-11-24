from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
GTFS = DATA / "gtfs"
GPS = DATA / "gps"            # unpacked daily SQLite files (deleted after processing)
EVENTS = DATA / "events"      # per-day stop-to-stop observations (parquet)
MODEL = DATA / "model"        # final model tables
ARCHIVE = RAW / "delhi-dtc-bus-gtfs-rt-2026-10.7z"

for p in (EVENTS, MODEL):
    p.mkdir(parents=True, exist_ok=True)

# Public holidays in October 2026 (treated like Sundays).
HOLIDAYS = {"2026-10-02", "2026-10-20"}  # Gandhi Jayanti, Dussehra
