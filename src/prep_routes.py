"""Step 1: prepare the geometry of every bus route.

For each route we pick its main stop pattern (the one most trips use), then
work out where each stop sits along the route's road path, as a distance in
metres from the start ("chainage"). Later, every GPS point is also turned into
a chainage, so "has the bus passed stop 7 yet?" becomes a simple comparison of
two numbers.

Outputs (data/model/):
  route_stops.parquet   route_id, seq, stop_id, chain_m, off_m
  route_line.parquet    route_id, x, y, chain_m   (road path every ~10 m)
  sched_segments.parquet  timetable time between consecutive stops
"""
import duckdb
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from config import GTFS, MODEL
from geo import to_xy

STEP_M = 10.0


def densify(x, y, step=STEP_M):
    """Return points every `step` metres along a polyline, plus their chainage."""
    dx, dy = np.diff(x), np.diff(y)
    seg = np.hypot(dx, dy)
    keep = seg > 0
    x0, y0, dx, dy, seg = x[:-1][keep], y[:-1][keep], dx[keep], dy[keep], seg[keep]
    if len(seg) == 0:
        return x[:1], y[:1], np.zeros(1)
    start = np.concatenate([[0.0], np.cumsum(seg)[:-1]])
    n = np.maximum(1, np.ceil(seg / step).astype(int))
    idx = np.repeat(np.arange(len(seg)), n)
    frac = (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)) / np.repeat(n, n)
    xs = x0[idx] + dx[idx] * frac
    ys = y0[idx] + dy[idx] * frac
    cs = start[idx] + seg[idx] * frac
    total = start[-1] + seg[-1]
    return np.append(xs, x0[-1] + dx[-1]), np.append(ys, y0[-1] + dy[-1]), np.append(cs, total)


def place_stops(lx, ly, lc, sx, sy):
    """Find each stop's chainage, forcing stops to appear in order along the line.

    Ordering matters for loop routes, where the first and last stop are at the
    same place: the last stop must get the chainage near the END of the line.
    """
    tree = cKDTree(np.column_stack([lx, ly]))
    out_c, out_d = [], []
    prev = -1.0
    for x, y in zip(sx, sy):
        idx = tree.query_ball_point([x, y], r=150)
        cands = [i for i in idx if lc[i] >= prev - 20]
        if cands:
            # The line may pass near this stop more than once (loops). Take the first
            # pass (candidates within 400 m of the earliest one), then the closest point.
            first = min(lc[i] for i in cands)
            cands = [i for i in cands if lc[i] <= first + 400]
            i = min(cands, key=lambda i: (lx[i] - x) ** 2 + (ly[i] - y) ** 2)
        else:
            d, i = tree.query([x, y])
        out_c.append(max(lc[i], prev))
        out_d.append(float(np.hypot(lx[i] - x, ly[i] - y)))
        prev = out_c[-1]
    return np.array(out_c), np.array(out_d)


def main():
    con = duckdb.connect()
    con.execute(f"""
      CREATE TABLE st AS SELECT trip_id, stop_id, CAST(stop_sequence AS INT) seq,
        arrival_time FROM read_csv('{GTFS}/stop_times.txt', all_varchar=true, header=true)""")
    con.execute(f"CREATE TABLE trips AS SELECT * FROM read_csv('{GTFS}/trips.txt', all_varchar=true, header=true)")
    con.execute(f"CREATE TABLE stops AS SELECT stop_id, stop_name, CAST(stop_lat AS DOUBLE) lat, CAST(stop_lon AS DOUBLE) lon FROM read_csv('{GTFS}/stops.txt', all_varchar=true, header=true)")
    con.execute(f"""CREATE TABLE shapes AS SELECT shape_id, CAST(shape_pt_lat AS DOUBLE) lat, CAST(shape_pt_lon AS DOUBLE) lon,
        CAST(shape_pt_sequence AS INT) seq FROM read_csv('{GTFS}/shapes.txt', all_varchar=true, header=true)""")

    # Main pattern per route = most common (shape, stop list) combination.
    con.execute("""
      CREATE TABLE pat AS
      WITH p AS (SELECT trip_id, string_agg(stop_id, ',' ORDER BY seq) pattern FROM st GROUP BY 1)
      SELECT t.route_id, t.shape_id, p.pattern, count(*) n, min(t.trip_id) rep_trip
      FROM trips t JOIN p USING(trip_id) GROUP BY 1,2,3""")
    main_pat = con.execute("""
      SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY route_id ORDER BY n DESC, length(pattern) DESC) r FROM pat)
      WHERE r = 1""").df()

    stops = con.execute("SELECT * FROM stops").df().set_index("stop_id")
    shapes = {k: g.sort_values("seq") for k, g in con.execute("SELECT * FROM shapes").df().groupby("shape_id")}

    stop_rows, line_rows, bad = [], [], 0
    for r in main_pat.itertuples():
        sids = r.pattern.split(",")
        s = stops.loc[sids]
        sx, sy = to_xy(s.lat.values, s.lon.values)
        shp = shapes.get(r.shape_id)
        use_shape = shp is not None and len(shp) >= 2
        if use_shape:
            px, py = to_xy(shp.lat.values, shp.lon.values)
            lx, ly, lc = densify(px, py)
            c, d = place_stops(lx, ly, lc, sx, sy)
            # If stops sit far from the shape, the shape is wrong for this pattern.
            if np.median(d) > 120:
                use_shape = False
        if not use_shape:
            bad += 1
            lx, ly, lc = densify(sx, sy)
            c, d = place_stops(lx, ly, lc, sx, sy)
        stop_rows.append(pd.DataFrame({"route_id": r.route_id, "seq": np.arange(len(sids)), "stop_id": sids,
                                       "chain_m": c, "off_m": d}))
        line_rows.append(pd.DataFrame({"route_id": r.route_id, "x": lx.astype(np.float32),
                                       "y": ly.astype(np.float32), "chain_m": lc.astype(np.float32)}))

    rs = pd.concat(stop_rows, ignore_index=True)
    rl = pd.concat(line_rows, ignore_index=True)
    rs.to_parquet(MODEL / "route_stops.parquet", index=False)
    rl.to_parquet(MODEL / "route_line.parquet", index=False)

    # Timetable segment times: what the official schedule says each hop takes, by hour.
    con.execute("""
      CREATE TABLE sched AS
      WITH s AS (
        SELECT trip_id, stop_id, seq,
          CAST(split_part(arrival_time,':',1) AS INT)*3600 + CAST(split_part(arrival_time,':',2) AS INT)*60
            + CAST(split_part(arrival_time,':',3) AS INT) t FROM st),
      d AS (SELECT stop_id from_stop, lead(stop_id) OVER w to_stop, t, lead(t) OVER w - t dt
            FROM s WINDOW w AS (PARTITION BY trip_id ORDER BY seq))
      SELECT from_stop, to_stop, (t // 3600) % 24 AS hour, median(dt) sched_s, count(*) n
      FROM d WHERE to_stop IS NOT NULL AND dt >= 0 GROUP BY 1,2,3""")
    con.execute(f"COPY sched TO '{MODEL}/sched_segments.parquet' (FORMAT parquet)")

    print(f"routes: {len(main_pat)}  stops placed: {len(rs)}  line points: {len(rl)}  "
          f"routes using stop-path fallback: {bad}")
    print("stop distance to road path (m):", rs.off_m.describe(percentiles=[.5, .9, .99]).round(1).to_dict())


if __name__ == "__main__":
    main()
