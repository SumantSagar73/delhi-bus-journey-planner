# Technical note: Delhi bus travel-time model and journey planner

Transport Stack Hackathon 2026, Problem 1.

## 1. Idea

Every DTC bus reports its position every ~11 seconds. A bus that passes stop A at 08:31 and stop B at 08:36 has
just *measured* the A→B stretch of road at 08:30 on that day. In October 2026, 6,000+ buses made over 40 million
such measurements. We turn them into a table of **"how long does each stretch of road take, on each kind of day,
at each hour"**, and plan journeys with it instead of the fixed timetable.

```
GPS reports ──► clean ──► snap to route ──► time at each stop ──► stop-to-stop times
                                                                     │  (40M+ observations)
                                                                     ▼
                         stretch × day type × hour  ◄── aggregate + 4-level fallback
                                                                     │
  origin, destination, time ──► journey search (RAPTOR) ◄────────────┘
                                         │
                                         ▼
                        options + walk/wait/bus times + traffic effect
```

## 2. Linking GPS points to roads and routes (`prep_routes.py`, `gps_process.py`)

**Route geometry.** For each of the 2,574 GTFS routes we take its main stop pattern (the one most trips use) and
its road shape from `shapes.txt`, resampled every 10 m. Each stop is placed on the shape as a distance along the
route ("chainage"). Placement is forced to be in stop order, so loop routes, where the first and last stop are at
the same spot, get the right chainage. Median distance from a stop to its placed point: **3 m**.

**Matching GPS.** Each report carries a `route_id` that matches GTFS for **99.9%** of points, so we know which
route's road the bus is on. We don't need a general road map-matcher: we snap each point to the nearest point
on *that route's* shape (KD-tree), which turns it into a chainage.

**Cleaning noisy GPS.**
- About 37% of reports are exact duplicates (same bus, same second): dropped.
- Points more than 60 m from the route's road (GPS jumps, depot moves): dropped.
- A 5-point rolling median of chainage: one bad point can't push the bus forward or back.
- A running maximum: buses don't move backwards along a route.
- A run is split when reports stop for over 10 minutes, or when the bus jumps back over 500 m (a new trip began).

**Time at each stop.** The moment the bus passes 25 m beyond a stop is interpolated between the two reports on
either side. If those reports are more than 2 minutes apart, the crossing is not trusted and dropped. This handles
reports that arrive late or not at all. Consecutive trusted crossings give one **stop-to-stop observation**.
Speeds above 70 km/h are rejected as physically impossible.

## 3. Estimating travel time on each stretch (`build_model.py`)

**What a stretch time includes.** We time from *leaving* one stop to *leaving* the next. So each stretch includes
the driving, the traffic-signal waits and the dwell at the next stop: exactly what a passenger sitting on the
bus experiences. We chose not to model dwell and signals separately. The GPS doesn't record door openings,
and for a rider the total is what matters.

**Stretches are shared.** A stretch is identified by its two stop IDs, not by the route, so every route that uses
the same road pools its measurements.

**Outliers.** Per stretch, observations further than 4 robust standard deviations (median ± 4×1.4826×MAD, in
log-time) are removed, for example a breakdown or a driver break. About 1.5% are removed.

**Day types.** Weekday / Saturday / Sunday-or-holiday. Gandhi Jayanti (2 Oct) and Dussehra (20 Oct) count as holidays.

**Four levels of fallback.** Some stretches have few buses at some hours. Each estimate uses the most specific level
that has data:

| Level | Source | Used when |
|---|---|---|
| L1 | this stretch, this day type, this hour | it has observations |
| L2 | this stretch's all-day typical time × citywide hour profile for that day type | stretch measured, but not at this hour |
| L3 | median speed of up to 8 measured stretches within 1.5 km, at this day type and hour | stretch never measured (e.g. cluster-bus-only roads) |
| L4 | citywide average bus speed at this day type and hour | nothing nearby either |

L1 and L2 are **blended, not switched**: with *n* observations, `log t = (n·L1 + 4·L2)/(n + 4)`. One noisy bus
barely moves the answer, while 30 buses dominate it. Averages are taken in log-time (robust to outliers), then
multiplied by each stretch's mean/typical ratio, because the expected time of a long-tailed trip is its mean.

We also keep the **85th percentile** per stretch and hour, which the planner shows as "on a bad day".

**Service frequency.** The waiting time at a stop is half the gap between buses. The gap comes from the number of
distinct bus runs actually observed per route per hour in the GPS, which is more realistic than the timetable.
Routes with no GPS (cluster buses) use the timetable frequency.

## 4. Journey planning (`planner.py`)

A frequency-based version of **RAPTOR**, the round-based algorithm used by production planners:

1. Round 0: walk (straight line × 1.3 for real streets, 1.2 m/s) to every stop within 1 km of the origin.
   Stops with the same name within 600 m are grouped into "places" for the dropdown.
2. Rounds 1–3: ride every route from every stop reached. On-bus time is accumulated stretch by stretch, and each
   stretch uses the model value for the hour *at which the bus reaches it*. So a 7:45 departure correctly runs into
   8 am traffic. Between rounds, riders can walk up to 400 m to change buses. Each change costs a 2-minute comfort penalty.
3. Walk from the best stops to the destination.

The planner returns the fastest journey for each number of changes, plus alternatives found by excluding the first
bus of the best journey and searching again. For each journey it also reports:
- **the same buses re-timed at every hour 05:00–23:00**: the "traffic effect" and the quietest hour;
- **a bad-day time** (85th percentile) and **the timetable time**, for comparison;
- **data quality**: the share of the ride timed from levels L1/L2 (direct measurements).

## 5. Combining live and historical data

The historical model is the backbone. Live data plugs in as a correction factor on top of it.

- Live GTFS-RT positions go through **exactly the same pipeline** (`process_route` in `gps_process.py`), giving
  stop-to-stop observations from the last 30 minutes.
- For each stretch with live observations: `live ratio = observed / historical` for that hour. That ratio is
  spread to stretches within ~1 km on the same corridor, and blended in with weight `n_live / (n_live + 3)`, so one
  bus can't swing the answer.
- With no live data on a road (night, rarely served roads, or the feed is down), the ratio is 1 and the planner
  uses the historical model, with its own fallbacks. **The system never depends on live data being present.**

**Status:** the live DTC feed is not yet on the Transport Stack portal (its listing says only cluster-bus GPS is
live so far). The historical model, fallbacks and planner are built and validated. The live correction layer above
is the design. It reuses the existing per-route processing code, but it is not wired into the planner yet. That is
the first Phase 2 task.

## 6. Results (see VALIDATION.md)

Held-out test: model built from 1–24 Oct, tested on 28,000 real bus rides from 25–31 Oct (5–30 stops each).

| method | mean abs. error | rides within ±20% |
|---|---|---|
| **Our model** | **2.7 min** | **72%** |
| Same GPS data, no time of day | 3.9 min | 55% |
| Official timetable | 4.8 min | 41% |

The timetable assumes about the same time per stop all day. Real weekday buses take about 76 s per stop at 5 am and
158 s at 6 pm, and the model follows that curve. The main remaining error is a trend: the test week (the run-up to
Diwali) was slower than the training weeks, so weekday evenings are predicted about 7% too fast. The live
correction layer is designed to close that gap.

Data used: 38.4 million stop-to-stop observations from 31 days. 57% of model values come from a stretch's own
hourly measurements (L1), 33% from its all-day profile (L2), 10% from nearby roads (L3), and 0.4% from the citywide
average (L4).

## 7. Limitations and next steps

- Each route uses its main stop pattern. Rare variants (short turns, detours) are not modelled separately.
- Waiting time is frequency-based (half the headway), not tied to a specific scheduled departure.
- Cluster buses have no GPS in this dataset. Their roads borrow speeds from DTC buses on the same or nearby
  stretches (levels L1–L3).
- Walking uses straight-line distance × 1.3, not a street network.
- Next: live GTFS-RT ingestion once the DTC feed is published; metro legs for multimodal trips; per-stop dwell
  analysis to separate stop time from congestion.
