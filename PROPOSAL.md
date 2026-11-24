# Proposal: Delhi buses as traffic sensors

**Transport Stack Hackathon 2026, Problem 1: real-time bus traffic model and journey planner**
Repository: https://github.com/SumantSagar73/delhi-bus-journey-planner

## The problem

Delhi's bus timetable assumes every stretch of road takes the same time at every hour. A commuter can't tell
whether a trip will take 30 minutes or 60. The GPS data shows the timetable assumes about **106 seconds per
stop all day**, while real buses take **76 s at 5 am and 158 s at 6 pm**.

## Our solution

We use the 6,000+ DTC buses as moving traffic sensors.

1. **Learn real travel times.** One month of GPS (October 2026, 550M+ position reports) is cleaned, snapped to each
   bus's route, and turned into **38.4 million stop-to-stop measurements**.
2. **Build a traffic model.** It gives the time for every stretch of road, for weekday / Saturday / Sunday, for
   each hour. When a road has little data, it falls back in 4 steps: the stretch's own hourly data, then its
   all-day profile, then nearby roads, then the citywide average. So every query gets a sensible answer.
3. **Plan journeys.** A RAPTOR-style planner finds bus options with walking and up to 2 changes. On-bus time comes
   from the model for the hour the bus actually reaches each road.
4. **Serve it.** A documented API (`GET /journeys?from=…&to=…&depart=…`) and a map web app. For each option the
   app shows the buses, where to change, walk, wait and ride times, a "bad day" time, the timetable time, and how
   long the same trip takes at a quiet hour.

## Does it work?

Tested on **28,000 real bus rides from 25–31 Oct** that the model never saw (it was trained on 1–24 Oct):

| | average error | rides within ±20% |
|---|---|---|
| **Our model** | **2.7 min** | **72%** |
| Official timetable | 4.8 min | 41% |

That's **43% lower error than the timetable**. About half of the gain comes from modelling time of day. Details
are in VALIDATION.md, which also compares against Google Maps for 10 routes at 4 times of day.

## Impact

- **Commuters:** honest, time-of-day-aware journey times, plus a "bad day" figure for planning.
- **DTC / Transport Department:** a citywide map of bus speeds by hour that shows where buses lose time, which
  is useful for bus-lane and signal-priority decisions.
- **App developers:** an open API on Transport Stack data.

## Phase 2 plan

1. **Live layer:** blend live GTFS-RT positions into the historical model (same processing pipeline, designed in
   the technical note) to catch day-specific congestion, such as the pre-Diwali slowdown our validation found.
2. **Recency weighting** of history, so the model adapts to seasonal trends.
3. **Exact departures:** use real-time bus positions to predict the actual next bus instead of half the headway.
4. **Multimodal:** add metro legs using DMRC GTFS from Transport Stack.
5. **Corridor analytics:** rank the slowest stretches by hour as a planning tool for DTC.
