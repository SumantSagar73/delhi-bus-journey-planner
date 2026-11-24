"""Step 7: validation.

Part A, against real bus trips (held out)
  The model is built ONLY from training days (e.g. 1-24 Oct). From the test days
  (25-31 Oct) we cut real bus rides out of the GPS data: "bus on route R boarded
  stop a at 08:42 and reached stop b 23 min later". For each ride we ask:
    * our model       (time-of-day aware, GPS-learned)
    * flat model      (same GPS data but one average for all hours: shows what
                       time-of-day adds)
    * the timetable   (what the official schedule says)
  and compare with what really happened.

Part B, against Google Maps
  A list of origin-destination pairs and times with our door-to-door estimate.
  Google's numbers have to be looked up by hand (no free API), so the CSV has
  an empty column to fill in. Re-running this script adds the comparison.

Usage:
  python build_model.py --train-until 2026-10-24 --out ../data/model_val
  python validate.py --model ../data/model_val --test-from 2026-10-25
Writes VALIDATION.md and validation/*.csv in the project root.
"""
import argparse
from datetime import datetime

import duckdb
import numpy as np
import pandas as pd

import config
from build_model import daytype
from planner import Planner

OUT = config.ROOT / "validation"
OUT.mkdir(exist_ok=True)
RNG = np.random.default_rng(42)
LENGTHS = [5, 10, 20, 30]           # stops per sampled ride
GOOGLE_PAIRS = [
    ("ISBT Kashmere Gate", "Nehru Place"),
    ("Anand Vihar ISBT", "Dhaula Kuan"),
    ("Dwarka Sector 1", "AIIMS"),
    ("Jahangirpuri Metro Station GT Road", "ISBT Kashmere Gate"),
    ("Nehru Place", "Shivaji Stadium Terminal ( Connaught Place )"),
    ("Mehrauli Terminal", "ISBT Sarai Kale Khan"),
    ("Rohini Sec 22 Terminal", "Azadpur Terminal"),
    ("Badarpur Border (T)", "ITO Ring Road"),
    ("Uttam Nagar Terminal", "Rajouri Garden"),
    ("Mayur Vihar Phase III (T) Paper Market", "Lajpat Nagar"),
]
GOOGLE_TIMES = ["08:30", "13:00", "18:30", "22:30"]


def sample_rides(test_days, n_per_day=4000):
    con = duckdb.connect()
    con.execute("SET memory_limit='1000MB'")
    files = ", ".join(f"'{config.EVENTS}/segments_{d}.parquet'" for d in test_days)
    # contiguous runs of consecutive stops (no missing hop) inside one bus run
    df = con.execute(f"""
      WITH e AS (SELECT day, route_id, run, seq, t_from, dt,
                   seq - row_number() OVER (PARTITION BY day, route_id, run ORDER BY seq) grp
                 FROM read_parquet([{files}]) WHERE dt > 0 AND dt < 3600)
      SELECT day, route_id, run, grp, list(seq ORDER BY seq) seqs, list(t_from ORDER BY seq) ts, list(dt ORDER BY seq) dts
      FROM e GROUP BY 1,2,3,4 HAVING count(*) >= 5""").df()
    rides = []
    for day, g in df.groupby("day"):
        g = g.sample(min(len(g), n_per_day), random_state=1)
        for r in g.itertuples():
            n = len(r.seqs)
            L = RNG.choice([x for x in LENGTHS if x <= n] or [n])
            a = RNG.integers(0, n - L + 1)
            rides.append((day, r.route_id, int(r.seqs[a]), int(r.seqs[a] + L), float(r.ts[a]),
                          float(np.sum(r.dts[a:a + L]))))
    return pd.DataFrame(rides, columns=["day", "route_id", "a", "b", "t_start_utc", "actual_s"])


def predict(p, rides):
    ridx = {rid: i for i, (rid, _, _) in enumerate(p.routes)}
    flat = np.nanmean(p.est[:, :, 6:23], axis=2)            # one value per stretch & day type
    out = []
    for r in rides.itertuples():
        i = ridx.get(r.route_id)
        if i is None:
            out.append((np.nan, np.nan, np.nan))
            continue
        dtype = daytype(r.day)
        t = (r.t_start_utc + 19800) % 86400                   # IST seconds since midnight
        model, _ = p.ride(i, r.a, r.b, dtype, t)
        sched, _ = p.ride(i, r.a, r.b, dtype, t, "sched")
        segs = p.routes[i][2][r.a:r.b]
        fl = float(np.sum([flat[s, dtype] if s >= 0 else np.nan for s in segs]))
        out.append((model, fl, sched))
    rides[["model_s", "flat_s", "timetable_s"]] = out
    rides["hour"] = (((rides.t_start_utc + 19800) % 86400) // 3600).astype(int)
    rides["daytype"] = [["weekday", "saturday", "sunday/holiday"][daytype(d)] for d in rides.day]
    return rides.dropna()


def metrics(df, col):
    err = (df[col] - df.actual_s) / 60
    pe = (df[col] - df.actual_s) / df.actual_s
    return {"MAE (min)": round(err.abs().mean(), 2), "MAPE": f"{pe.abs().median() * 100:.1f}%",
            "within ±20%": f"{(pe.abs() <= .2).mean() * 100:.0f}%", "bias (min)": round(err.mean(), 2)}


def band(h):
    return ("05-08 early" if h < 8 else "08-11 morning peak" if h < 11 else "11-17 midday" if h < 17
            else "17-21 evening peak" if h < 21 else "21-05 night")


def table(rows, cols):
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join("| " + " | ".join(str(r[c]) for c in cols) + " |\n" for r in rows)


def main(model_dir, test_from):
    p = Planner(model_dir)
    train_days = pd.read_csv(f"{model_dir}/train_days.csv").day.tolist()
    test_days = sorted(f.stem.split("_")[1] for f in config.EVENTS.glob("segments_*.parquet")
                       if f.stem.split("_")[1] >= test_from)
    print(f"train {train_days[0]}..{train_days[-1]} ({len(train_days)} days), test {test_days}")
    rides = predict(p, sample_rides(test_days))
    rides.to_csv(OUT / "rides_test.csv", index=False)
    print(f"{len(rides):,} held-out rides")

    md = ["# Validation report\n",
          f"Model built from **{len(train_days)} days** ({train_days[0]} to {train_days[-1]}). "
          f"Tested on **{len(rides):,} real bus rides** from **{len(test_days)} unseen days** ({test_days[0]} to {test_days[-1]}), "
          "cut from the GPS data: a bus on a given route, from one stop to another 5–30 stops later, at the time it actually ran.\n",
          "We compare three predictions of the time on the bus with what actually happened:\n",
          "- **Our model**: GPS-learned, by stretch of road, day type and hour.",
          "- **Flat model**: the same GPS data, but a single all-day average per stretch. Shows the value of modelling time of day.",
          "- **Timetable**: the official GTFS schedule.\n",
          "MAE = mean absolute error. MAPE = median absolute % error. Within ±20% = share of rides predicted within 20% of the real time. "
          "Bias > 0 means predicting too slow.\n",
          "## Overall\n"]
    rows = [{"method": name, **metrics(rides, col)} for name, col in
            [("Our model", "model_s"), ("Flat model (no time of day)", "flat_s"), ("Timetable", "timetable_s")]]
    md.append(table(rows, ["method", "MAE (min)", "MAPE", "within ±20%", "bias (min)"]))

    md.append("\n## By time of day\n")
    rows = []
    rides["band"] = rides.hour.map(band)
    for b, g in rides.groupby("band"):
        m, t = metrics(g, "model_s"), metrics(g, "timetable_s")
        rows.append({"time": b, "rides": len(g), "actual avg (min)": round(g.actual_s.mean() / 60, 1),
                     "model MAE": m["MAE (min)"], "model ±20%": m["within ±20%"],
                     "timetable MAE": t["MAE (min)"], "timetable ±20%": t["within ±20%"]})
    md.append(table(rows, list(rows[0])))

    md.append("\n## By ride length\n")
    rides["stops"] = rides.b - rides.a
    rows = []
    for L, g in rides.groupby("stops"):
        m, t = metrics(g, "model_s"), metrics(g, "timetable_s")
        rows.append({"stops": L, "rides": len(g), "actual avg (min)": round(g.actual_s.mean() / 60, 1),
                     "model MAE": m["MAE (min)"], "model MAPE": m["MAPE"], "timetable MAE": t["MAE (min)"], "timetable MAPE": t["MAPE"]})
    md.append(table(rows, list(rows[0])))

    md.append("\n## By day type\n")
    rows = []
    for d, g in rides.groupby("daytype"):
        m = metrics(g, "model_s")
        rows.append({"day type": d, "rides": len(g), **m})
    md.append(table(rows, list(rows[0])))

    # hour-of-day curve: does the model follow the real rush hour?
    hr = rides[rides.daytype == "weekday"].groupby("hour").apply(
        lambda g: pd.Series({"actual": (g.actual_s / (g.b - g.a)).mean(), "model": (g.model_s / (g.b - g.a)).mean(),
                             "timetable": (g.timetable_s / (g.b - g.a)).mean()}), include_groups=False)
    md.append("\n## Does it follow rush hour? (weekday, average seconds per stop-to-stop hop)\n")
    md.append(table([{"hour": f"{h:02d}:00", "actual": round(r.actual), "our model": round(r.model), "timetable": round(r.timetable)}
                     for h, r in hr.iterrows()], ["hour", "actual", "our model", "timetable"]))

    # ---- Part B: Google Maps ----
    gfile = OUT / "google_maps_comparison.csv"
    prev = pd.read_csv(gfile) if gfile.exists() else None
    grows = []
    for a, b in GOOGLE_PAIRS:
        for tm in GOOGLE_TIMES:
            try:
                res = p.plan(a, b, datetime.fromisoformat(f"2026-10-27T{tm}"), n_options=1)
                o = res["options"][0] if res["options"] else None
            except ValueError:
                o = None
            grows.append({"from": a, "to": b, "weekday_depart": tm,
                          "our_total_min": o["total_min"] if o else "", "our_routes": o["summary"] if o else "",
                          "our_in_bus_min": o.get("in_bus_min", "") if o else "",
                          "timetable_total_min": o.get("total_min_timetable", "") if o else "",
                          "google_maps_total_min": ""})
    g = pd.DataFrame(grows)
    if prev is not None and "google_maps_total_min" in prev:
        g = g.drop(columns="google_maps_total_min").merge(
            prev[["from", "to", "weekday_depart", "google_maps_total_min"]], on=["from", "to", "weekday_depart"], how="left")
    g.to_csv(gfile, index=False)
    md.append("\n## Comparison with Google Maps (door to door, weekday)\n")
    filled = g[pd.to_numeric(g.google_maps_total_min, errors="coerce").notna()].copy()
    if len(filled):
        filled["google"] = pd.to_numeric(filled.google_maps_total_min)
        filled["diff"] = filled.our_total_min - filled.google
        md.append(f"{len(filled)} pairs filled in. Mean absolute difference vs Google Maps: "
                  f"**{filled['diff'].abs().mean():.1f} min** (ours minus Google, average {filled['diff'].mean():+.1f} min).\n")
    else:
        md.append("_Google Maps column not filled in yet: see validation/google_maps_comparison.csv._\n")
    md.append(table(g.to_dict("records"), ["from", "to", "weekday_depart", "our_total_min", "our_routes",
                                           "timetable_total_min", "google_maps_total_min"]))
    md.append("\nGoogle Maps times are looked up by hand in Google Maps (public transport, bus only, same weekday and "
              "departure time) and typed into `validation/google_maps_comparison.csv`; re-running `validate.py` updates this section.\n")

    (config.ROOT / "VALIDATION.md").write_text("\n".join(md))
    print("\n".join(md[:12]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(config.DATA / "model_val"))
    ap.add_argument("--test-from", default="2026-10-25")
    a = ap.parse_args()
    main(a.model, a.test_from)
