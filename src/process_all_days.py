"""Step 3: run gps_process.py for every day of October.

One day at a time: unpack that day's database from the 7z, process it, delete
it. A full unpack would need 124 GB of disk; this way we never need more than ~5 GB.
Days already processed are skipped, so it is safe to re-run after a stop.
"""
import subprocess
import sys
import time
from datetime import date, timedelta

import py7zr

from config import ARCHIVE, EVENTS, GPS

GPS.mkdir(parents=True, exist_ok=True)
days = [(date(2026, 10, 1) + timedelta(d)).isoformat() for d in range(31)]

for day in days:
    if (EVENTS / f"segments_{day}.parquet").exists():
        print(f"{day}: already done", flush=True)
        continue
    name = f"bus_movements_{day.replace('-', '_')}.db"
    t = time.time()
    with py7zr.SevenZipFile(ARCHIVE) as z:
        z.extract(path=GPS, targets=[name])
    print(f"{day}: unpacked in {time.time() - t:.0f}s", flush=True)
    r = subprocess.run([sys.executable, "gps_process.py", day])
    (GPS / name).unlink(missing_ok=True)
    if r.returncode != 0:
        print(f"{day}: FAILED", flush=True)

print("ALL_DAYS_DONE", flush=True)
