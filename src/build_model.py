"""Step 4: combine every stop-to-stop observation into the travel-time model.

The model answers: "how many seconds does the stretch from stop A to stop B
take, on this kind of day (weekday / Saturday / Sunday-or-holiday), in this hour?"

Not every stretch has enough buses at every hour, so each estimate falls back
through four levels, from most to least specific:

  L1  this stretch, this day type, this hour        (its own measurements)
  L2  this stretch's all-day typical time, scaled by the citywide rush-hour
      profile for that day type and hour
  L3  nearby stretches (within 1.5 km) at that day type and hour: their speed
      times this stretch's length
  L4  citywide average bus speed at that day type and hour

L1 and L2 are blended rather than switched: with n measurements,
  estimate = (n * L1 + K * L2) / (n + K)       (computed on log-times, K = 4)
so 1 measurement barely moves the answer, while 30 measurements dominate it.

Usage:
  python build_model.py                 # model from all days -> data/model/
  python build_model.py --train-until 2026-10-24 --out data/model_val
      (model from 1-24 Oct only, so 25-31 Oct can be used to test it honestly)
"""
import argparse
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from config import EVENTS, HOLIDAYS, MODEL
from geo import to_xy
import config

K_SHRINK = 4.0
DAYTYPES = ["weekday", "saturday", "sunday"]


def daytype(day: str) -> int:
    if day in HOLIDAYS:
        return 2
    wd = date.fromisoformat(day).weekday()
    return 0 if wd < 5 else (1 if wd == 5 else 2)


def main(train_until=None, out=MODEL):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(EVENTS.glob("segments_*.parquet"))
    days = [f.stem.split("_")[1] for f in files]
    if train_until:
        days = [d for d in days if d <= train_until]
    if not days:
        raise SystemExit("no processed days found")
    print(f"building from {len(days)} days: {days[0]} .. {days[-1]}")

    con = duckdb.connect()
    con.execute("SET memory_limit='1200MB'")
    con.execute("CREATE TABLE dt_map (day VARCHAR, dtype INT)")
    con.executemany("INSERT INTO dt_map VALUES (?, ?)", [(d, daytype(d)) for d in days])
    flist = ", ".join(f"'{EVENTS}/segments_{d}.parquet'" for d in days)
    con.execute(f"""
      CREATE TABLE obs AS
      SELECT o.from_stop, o.to_stop, o.route_id, o.run, o.day, m.dtype,
             CAST(((o.t_from + 19800) % 86400) // 3600 AS INT) AS hour,   -- IST hour
             o.dt, o.dist_m
      FROM read_parquet([{flist}]) o JOIN dt_map m USING (day)""")

    # Robust cleaning: drop observations far outside the stretch's normal range
    # (bus broke down, driver break, bad GPS). Uses median +/- 4 x MAD in log space.
    con.execute("""
      CREATE TABLE seg_stats AS
      SELECT from_stop, to_stop, median(ln(dt)) mu FROM obs GROUP BY 1,2""")
    con.execute("""
      CREATE TABLE seg_mad AS
      SELECT o.from_stop, o.to_stop, s.mu, greatest(median(abs(ln(o.dt) - s.mu)), 0.1) mad
      FROM obs o JOIN seg_stats s USING (from_stop, to_stop) GROUP BY 1,2,3""")
    con.execute("""
      CREATE TABLE clean AS
      SELECT o.* FROM obs o JOIN seg_mad s USING (from_stop, to_stop)
      WHERE abs(ln(o.dt) - s.mu) <= 4 * 1.4826 * s.mad""")
    n_all, n_clean = con.execute("SELECT (SELECT count(*) FROM obs), (SELECT count(*) FROM clean)").fetchone()
    print(f"observations: {n_all:,}  kept after outlier removal: {n_clean:,} ({n_clean / n_all:.1%})")

    # L1: per stretch, day type, hour
    l1 = con.execute("""
      SELECT from_stop, to_stop, dtype, hour, count(*) n, avg(ln(dt)) mlog,
             quantile_cont(dt, 0.5) p50, quantile_cont(dt, 0.85) p85
      FROM clean GROUP BY 1,2,3,4""").df()
    # all-day typical per stretch
    seg = con.execute("""
      SELECT from_stop, to_stop, count(*) n_all, median(dt) med_all, median(dist_m) dist_m
      FROM clean GROUP BY 1,2""").df()
    # citywide hour profile: how much slower/faster than the stretch's typical time
    prof = con.execute("""
      SELECT c.dtype, c.hour, exp(median(ln(c.dt) - ln(s.med_all))) factor, count(*) n
      FROM clean c JOIN (SELECT from_stop, to_stop, median(dt) med_all FROM clean GROUP BY 1,2) s
      USING (from_stop, to_stop) GROUP BY 1,2""").df()
    city = con.execute("""
      SELECT dtype, hour, sum(dist_m) / sum(dt) speed_ms FROM clean GROUP BY 1,2""").df()
    # service frequency actually observed: distinct bus runs per route per hour per day
    freq = con.execute("""
      SELECT route_id, dtype, hour, count(DISTINCT run || day) / count(DISTINCT day) runs_per_hour
      FROM clean WHERE from_stop IN (SELECT from_stop FROM clean GROUP BY 1) GROUP BY 1,2,3""").df()

    # Fill gaps in the hour profile / city speed (e.g. 3 am Saturday) from neighbours.
    full = pd.MultiIndex.from_product([range(3), range(24)], names=["dtype", "hour"])
    prof = prof.set_index(["dtype", "hour"]).reindex(full)
    city = city.set_index(["dtype", "hour"]).reindex(full)
    for t in (prof, city):
        t.loc[:, :] = t.groupby(level=0).transform(lambda s: s.interpolate(limit_direction="both"))
        # a day type with no data at all borrows the other day types' average
        t.loc[:, :] = t.fillna(t.groupby(level=1).transform("mean"))
    prof_arr = prof["factor"].values.reshape(3, 24)
    city_arr = city["speed_ms"].values.reshape(3, 24)

    # ----- the final table: every stretch any route uses, x 3 day types x 24 hours -----
    rs = pd.read_parquet(MODEL / "route_stops.parquet").sort_values(["route_id", "seq"])
    rs["to_stop"] = rs.groupby("route_id").stop_id.shift(-1)
    rs["dist"] = rs.groupby("route_id").chain_m.shift(-1) - rs.chain_m
    pairs = (rs.dropna(subset=["to_stop"]).rename(columns={"stop_id": "from_stop"})
             .groupby(["from_stop", "to_stop"], as_index=False).dist.median())
    pairs["dist"] = pairs.dist.clip(lower=20)
    pairs = pairs.merge(seg, on=["from_stop", "to_stop"], how="left")
    pairs["dist"] = pairs.dist_m.astype("float64").fillna(pairs.dist).clip(lower=20)
    pairs = pairs.reset_index(drop=True)
    P = len(pairs)
    key = {(a, b): i for i, (a, b) in enumerate(zip(pairs.from_stop, pairs.to_stop))}

    # stop coordinates for the spatial fallback
    stops = pd.read_csv(config.GTFS / "stops.txt", dtype={"stop_id": str}).set_index("stop_id")
    fa = stops.loc[pairs.from_stop]
    ta = stops.loc[pairs.to_stop]
    mx, my = to_xy((fa.stop_lat.values + ta.stop_lat.values) / 2, (fa.stop_lon.values + ta.stop_lon.values) / 2)

    est = np.full((P, 3, 24), np.nan, dtype=np.float32)
    level = np.zeros((P, 3, 24), dtype=np.int8)
    nobs = np.zeros((P, 3, 24), dtype=np.int32)
    p85 = np.full((P, 3, 24), np.nan, dtype=np.float32)

    # L2 prior for stretches with any data
    has = pairs.med_all.notna().values
    prior = np.log(pairs.med_all.values[:, None, None] * prof_arr[None, :, :])

    # L1 blended with the L2 prior
    l1["i"] = [key.get((a, b), -1) for a, b in zip(l1.from_stop, l1.to_stop)]
    l1 = l1[l1.i >= 0]
    i, d, h = l1.i.values, l1.dtype.values, l1.hour.values
    nobs[i, d, h] = l1.n.values
    p85[i, d, h] = l1.p85.values
    blended = (l1.n.values * l1.mlog.values + K_SHRINK * prior[i, d, h]) / (l1.n.values + K_SHRINK)
    est[i, d, h] = np.exp(blended)
    level[i, d, h] = 1
    m2 = has[:, None, None] & np.isnan(est)
    est[m2] = np.exp(np.broadcast_to(prior, est.shape)[m2])
    level[m2] = 2

    # Averaging in log space (robust to outliers) gives a "typical" time that sits
    # below the true average, because slow trips are long-tailed. Expected travel
    # time = mean, so scale up by each stretch's mean/typical ratio (shrunk to the
    # citywide ratio for stretches with few observations).
    corr = con.execute("""
      WITH g AS (SELECT from_stop, to_stop, count(*) n, avg(dt) am, exp(avg(ln(dt))) gm
                 FROM clean GROUP BY from_stop, to_stop, dtype, hour)
      SELECT from_stop, to_stop, sum(n * am) / sum(n * gm) ratio, sum(n) n FROM g GROUP BY 1,2""").df()
    glob = float((corr.ratio * corr.n).sum() / corr.n.sum())
    corr["ratio"] = (corr.n * corr.ratio + 50 * glob) / (corr.n + 50)
    ratio = np.full(P, glob)
    ci = np.array([key.get((a, b), -1) for a, b in zip(corr.from_stop, corr.to_stop)])
    ratio[ci[ci >= 0]] = corr.ratio.values[ci >= 0]
    est[has] *= ratio[has, None, None]
    print(f"mean/typical correction: citywide x{glob:.3f}")

    # L3: borrow speed from nearby measured stretches at the same day type / hour
    measured = np.where(has)[0]
    tree = cKDTree(np.column_stack([mx[measured], my[measured]]))
    need = np.where(~has)[0]
    if len(need):
        dist_nb, idx_nb = tree.query(np.column_stack([mx[need], my[need]]), k=8, distance_upper_bound=1500)
        for row, (dn, ix) in enumerate(zip(dist_nb, idx_nb)):
            ok = np.isfinite(dn)
            if ok.sum() < 3:
                continue
            nb = measured[ix[ok]]
            speeds = pairs.dist.values[nb, None, None] / est[nb]          # m/s per dtype, hour
            p = need[row]
            with np.errstate(all="ignore"):
                v = pairs.dist.values[p] / np.nanmedian(speeds, axis=0)
            ok3 = np.isfinite(v)
            est[p][ok3] = v[ok3]
            level[p][ok3] = 3
    # L4: citywide speed
    m4 = np.isnan(est)
    est[m4] = (pairs.dist.values[:, None, None] / city_arr[None])[m4]
    level[m4] = 4

    np.savez_compressed(out / "segment_model.npz", est=est, p85=p85, level=level, nobs=nobs,
                        from_stop=np.array(pairs.from_stop.tolist(), dtype="U"), to_stop=np.array(pairs.to_stop.tolist(), dtype="U"),
                        dist=pairs.dist.values.astype(np.float32), prof=prof_arr, city=city_arr)
    freq.to_parquet(out / "route_freq.parquet", index=False)
    pd.DataFrame({"day": days}).to_csv(out / "train_days.csv", index=False)

    lv = level.reshape(-1)
    print(f"stretches: {P:,}  estimates: {lv.size:,}")
    for L in (1, 2, 3, 4):
        print(f"  L{L}: {np.mean(lv == L):.1%}")
    print("citywide speed km/h (weekday) by hour:", np.round(city_arr[0] * 3.6, 1).tolist())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-until")
    ap.add_argument("--out", default=str(MODEL))
    a = ap.parse_args()
    main(a.train_until, a.out)
