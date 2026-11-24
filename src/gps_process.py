"""Step 2: turn one day of raw GPS into stop-to-stop travel times.

For each bus on each trip:
  1. Clean:   drop duplicate reports; drop points more than 60 m from the route's
              road (GPS jumps); smooth with a rolling median so one bad point
              can't drag the bus forward or backward.
  2. Match:   turn every point into "metres along the route" (chainage) by
              snapping it to the nearest point on the route's road path.
  3. Measure: find the moment the bus passed each stop (interpolating between
              the two GPS reports either side of it). If those two reports are
              more than 2 minutes apart we don't trust the estimate and skip it.
  4. Record:  time between passing consecutive stops = one observation of how
              long that stretch of road takes at that time of day.

The time at a stop is when the bus passes 25 m beyond it, i.e. when it leaves.
So each stop-to-stop time includes the wait at the next stop and at signals:
exactly what a passenger experiences.

Usage: python gps_process.py 2026-10-20   (needs data/gps/bus_movements_2026_10_20.db)
Output: data/events/segments_2026-10-20.parquet
"""
import sys
import time

import duckdb
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from config import EVENTS, GPS, MODEL
from geo import to_xy

MAX_OFF_ROUTE_M = 60      # points further than this from the road are noise
MAX_GAP_S = 120           # don't interpolate a stop crossing across a bigger gap
RUN_BREAK_S = 600         # 10 min with no report = treat as a new run
BACKWARD_RESET_M = 500    # bus jumped back to the start = a new trip began
PASS_OFFSET_M = 25        # "passed the stop" = 25 m beyond it
MAX_SPEED_MS = 70 / 3.6   # stop-to-stop speeds above 70 km/h are impossible here
SMOOTH = 5                # rolling-median window (points)


def load_day(con, day):
    db = GPS / f"bus_movements_{day.replace('-', '_')}.db"
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"""
      CREATE TABLE pts AS
      SELECT DISTINCT
        CAST(CAST(route_id AS BIGINT) AS VARCHAR) route_id,
        hash(vehicle_id || '|' || trip_id) run_key,
        CAST(timestamp AS BIGINT) ts,
        CAST(lat AS DOUBLE) lat, CAST(lng AS DOUBLE) lon
      FROM sqlite_scan('{db}', 'vehicle_feed')
      WHERE route_id IS NOT NULL""")
    return con.execute("SELECT count(*) FROM pts").fetchone()[0]


def split_runs(ts, chain):
    """Yield index ranges for clean, forward-moving pieces of one run."""
    n = len(ts)
    breaks = np.where((np.diff(ts) > RUN_BREAK_S) | (np.diff(chain) < -BACKWARD_RESET_M))[0] + 1
    bounds = np.concatenate([[0], breaks, [n]])
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a >= 5:
            yield a, b


def process_route(route_id, df, line, stops):
    """df: GPS points for one route, sorted by run_key, ts."""
    tree, lc = line
    x, y = to_xy(df.lat.values, df.lon.values)
    dist, idx = tree.query(np.column_stack([x, y]), distance_upper_bound=MAX_OFF_ROUTE_M)
    ok = np.isfinite(dist)
    df = df.loc[ok]
    chain_raw = lc[idx[ok]]
    df = df.assign(chain=chain_raw)

    s_chain = stops.chain_m.values
    s_pass = np.minimum(s_chain + PASS_OFFSET_M, lc[-1])
    s_id = stops.stop_id.values

    out = []
    for run_key, g in df.groupby("run_key", sort=False):
        if len(g) < 5:
            continue
        ts = g.ts.values.astype(np.float64)
        ch = pd.Series(g.chain.values).rolling(SMOOTH, center=True, min_periods=1).median().values
        for a, b in split_runs(ts, ch):
            t, c = ts[a:b], np.maximum.accumulate(ch[a:b])
            # stops this piece fully covers
            k = np.where((s_pass > c[0]) & (s_pass <= c[-1]))[0]
            if len(k) < 2:
                continue
            j = np.searchsorted(c, s_pass[k], side="left")
            j = np.clip(j, 1, len(c) - 1)
            t0, t1, c0, c1 = t[j - 1], t[j], c[j - 1], c[j]
            frac = np.where(c1 > c0, (s_pass[k] - c0) / np.maximum(c1 - c0, 1e-9), 1.0)
            tp = t0 + frac * (t1 - t0)
            good = (t1 - t0) <= MAX_GAP_S
            # consecutive good stops -> one segment observation each
            pair = good[:-1] & good[1:] & (np.diff(k) == 1)
            if not pair.any():
                continue
            ii = np.where(pair)[0]
            out.append(pd.DataFrame({
                "route_id": route_id,
                "run": run_key,
                "seq": k[ii],
                "from_stop": s_id[k[ii]],
                "to_stop": s_id[k[ii] + 1],
                "t_from": tp[ii],
                "dt": tp[ii + 1] - tp[ii],
                "dist_m": s_chain[k[ii] + 1] - s_chain[k[ii]],
            }))
    if not out:
        return None
    seg = pd.concat(out, ignore_index=True)
    # physically impossible values come from bad matches
    seg = seg[(seg.dt > 0) & (seg.dist_m / seg.dt.clip(lower=1) <= MAX_SPEED_MS)]
    return seg


def main(day):
    t_start = time.time()
    con = duckdb.connect()
    con.execute("SET memory_limit='1500MB'")
    n = load_day(con, day)

    lines = pd.read_parquet(MODEL / "route_line.parquet")
    rstops = pd.read_parquet(MODEL / "route_stops.parquet")
    line_by_route = {r: g for r, g in lines.groupby("route_id")}
    stops_by_route = {r: g.sort_values("seq") for r, g in rstops.groupby("route_id")}
    del lines

    routes = [r for (r,) in con.execute("SELECT DISTINCT route_id FROM pts").fetchall()]
    results, n_used, skipped = [], 0, 0
    for i, r in enumerate(routes):
        if r not in line_by_route:
            skipped += 1
            continue
        g = line_by_route[r]
        line = (cKDTree(np.column_stack([g.x.values, g.y.values])), g.chain_m.values.astype(np.float64))
        df = con.execute("SELECT run_key, ts, lat, lon FROM pts WHERE route_id = ? ORDER BY run_key, ts", [r]).df()
        n_used += len(df)
        seg = process_route(r, df, line, stops_by_route[r])
        if seg is not None:
            results.append(seg)

    seg = pd.concat(results, ignore_index=True)
    seg["day"] = day
    seg["t_from"] = seg.t_from.round().astype("int64")
    seg["dt"] = seg.dt.astype("float32")
    seg["dist_m"] = seg.dist_m.astype("float32")
    seg.to_parquet(EVENTS / f"segments_{day}.parquet", index=False)
    print(f"{day}: {n:,} unique points, {len(routes)} routes ({skipped} not in GTFS), "
          f"{len(seg):,} stop-to-stop observations, {time.time() - t_start:.0f}s")


if __name__ == "__main__":
    main(sys.argv[1])
