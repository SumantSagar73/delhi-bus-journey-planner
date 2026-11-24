"""Step 5: the journey planner.

Given an origin, a destination and a departure time, find good bus journeys.

How it searches (a simplified version of the RAPTOR algorithm used by real
journey planners):
  Round 0: walk from the origin to every stop within ~1 km.
  Round 1: from every stop reached, ride every route that serves it.
           Times on the bus come from the GPS-learned model, hour by hour:
           if the bus reaches a stretch at 9:10, the 9 am time is used.
  Round 2, 3: change buses (optionally walking a few hundred metres to a nearby
           stop) and ride again. So up to 2 changes.
  At the end, walk from the best stops to the destination.

Waiting for a bus: we don't know exactly when the next bus comes, so we use
half the gap between buses on that route at that hour (measured from GPS where
we have it, otherwise from the timetable).

For each journey we also re-time the same buses at every hour of the day, so
the user can see the effect of traffic ("at 11 pm this takes 35 min").
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

import config
from build_model import daytype
from geo import to_xy

WALK_SPEED = 1.2          # m/s, about 4.3 km/h
WALK_DETOUR = 1.3         # real streets are ~30% longer than a straight line
MAX_ACCESS_M = 1000       # straight-line distance we'll walk to the first stop / from the last
MAX_TRANSFER_M = 400      # walking between stops when changing buses
MAX_WAIT_S = 30 * 60
TRANSFER_PENALTY_S = 120  # a change of bus "feels" 2 min longer; avoids pointless changes
MAX_ROUNDS = 3            # up to 2 changes


def walk_s(m):
    return m * WALK_DETOUR / WALK_SPEED


@dataclass
class Leg:
    kind: str                     # "walk" or "bus"
    start: float                  # seconds since midnight
    end: float
    from_name: str = ""
    to_name: str = ""
    from_stop: str | None = None
    to_stop: str | None = None
    route_id: str | None = None
    route_name: str | None = None
    headsign: str | None = None
    wait_s: float = 0.0
    n_stops: int = 0
    distance_m: float = 0.0
    seg_idx: list = field(default_factory=list)   # model stretch indices ridden
    path: list = field(default_factory=list)      # [[lat, lon], ...] for the map
    data_level: dict = field(default_factory=dict)


class Planner:
    def __init__(self, model_dir: Path = config.MODEL):
        model_dir = Path(model_dir)
        m = np.load(model_dir / "segment_model.npz", allow_pickle=False)
        self.est, self.p85, self.level, self.nobs = m["est"], m["p85"], m["level"], m["nobs"]
        self.city = m["city"]
        self.seg_key = {(a, b): i for i, (a, b) in enumerate(zip(m["from_stop"], m["to_stop"]))}
        sched = pd.read_parquet(config.MODEL / "sched_segments.parquet")
        self.sched = {(a, b, h): s for a, b, h, s in zip(sched.from_stop, sched.to_stop, sched.hour, sched.sched_s)}

        stops = pd.read_csv(config.GTFS / "stops.txt", dtype={"stop_id": str})
        self.stop_ids = stops.stop_id.values
        self.stop_idx = {s: i for i, s in enumerate(self.stop_ids)}
        self.stop_name = stops.stop_name.values
        self.stop_lat, self.stop_lon = stops.stop_lat.values, stops.stop_lon.values
        sx, sy = to_xy(self.stop_lat, self.stop_lon)
        self.stop_xy = np.column_stack([sx, sy])
        self.tree = cKDTree(self.stop_xy)

        routes = pd.read_csv(config.GTFS / "routes.txt", dtype={"route_id": str})
        self.route_name = dict(zip(routes.route_id, routes.route_short_name))
        self.route_desc = dict(zip(routes.route_id, routes.route_desc))

        rs = pd.read_parquet(config.MODEL / "route_stops.parquet").sort_values(["route_id", "seq"])
        self.routes = []          # list of (route_id, stop index array, stretch index array)
        self.stop_routes = [[] for _ in self.stop_ids]
        for rid, g in rs.groupby("route_id", sort=False):
            st = np.array([self.stop_idx[s] for s in g.stop_id.values])
            segs = np.array([self.seg_key.get((a, b), -1) for a, b in zip(g.stop_id.values[:-1], g.stop_id.values[1:])])
            r = len(self.routes)
            self.routes.append((rid, st, segs))
            for pos, s in enumerate(st[:-1]):           # can't board at the last stop
                self.stop_routes[s].append((r, pos))

        # buses per hour: GPS-observed where available, else timetable
        self.freq = np.zeros((len(self.routes), 3, 24), dtype=np.float32)
        ridx = {rid: i for i, (rid, _, _) in enumerate(self.routes)}
        sf = pd.read_parquet(config.MODEL / "sched_freq.parquet")
        for rid, h, n in zip(sf.route_id, sf.hour, sf.trips_per_hour):
            if rid in ridx:
                self.freq[ridx[rid], :, h] = n
        gf = pd.read_parquet(model_dir / "route_freq.parquet")
        for rid, d, h, n in zip(gf.route_id, gf.dtype, gf.hour, gf.runs_per_hour):
            if rid in ridx and n > 0:
                self.freq[ridx[rid], d, h] = max(n, self.freq[ridx[rid], d, h] * 0.5)

        # walking links between nearby stops
        pairs = self.tree.query_pairs(MAX_TRANSFER_M, output_type="ndarray")
        self.foot = [[] for _ in self.stop_ids]
        d = np.hypot(*(self.stop_xy[pairs[:, 0]] - self.stop_xy[pairs[:, 1]]).T)
        for (a, b), dd in zip(pairs, d):
            self.foot[a].append((b, walk_s(dd)))
            self.foot[b].append((a, walk_s(dd)))

        # route shapes for drawing on the map
        self.route_line = None

        # name search index
        self._name_tokens = [set(self._tokens(n)) for n in self.stop_name]
        self._build_places()

    # ------------------------------------------------------------------ places
    def _build_places(self):
        """Group stops into places for the dropdown: same name and within 600 m.

        Delhi has e.g. 7 different 'ESI Hospital' stops in different areas, so a
        name alone isn't a place. Duplicated names get a nearby landmark as a hint.
        """
        norm = [re.sub(r"\s+", " ", str(n)).strip() for n in self.stop_name]
        by_name = {}
        for i, n in enumerate(norm):
            by_name.setdefault(n.lower(), []).append(i)
        places = []
        for key, idx in by_name.items():
            idx = list(idx)
            while idx:
                seed = idx[0]
                d = np.hypot(*(self.stop_xy[idx] - self.stop_xy[seed]).T)
                grp = [i for i, dd in zip(idx, d) if dd <= 600]
                idx = [i for i in idx if i not in grp]
                xy = self.stop_xy[grp].mean(axis=0)
                n_routes = len({r for s in grp for r, _ in self.stop_routes[s]})
                places.append({"name": norm[grp[0]], "stops": grp, "xy": xy, "routes": n_routes,
                               "lat": float(np.mean(self.stop_lat[grp])), "lon": float(np.mean(self.stop_lon[grp]))})
        count = {}
        for p in places:
            count[p["name"].lower()] = count.get(p["name"].lower(), 0) + 1
        for p in places:
            p["hint"] = ""
            if count[p["name"].lower()] > 1:
                # nearest stop with a different name = landmark hint
                for j in self.tree.query(p["xy"], k=12)[1]:
                    if norm[j].lower() != p["name"].lower():
                        p["hint"] = "near " + norm[j]
                        break
        places.sort(key=lambda p: (-p["routes"], p["name"]))
        for k, p in enumerate(places):
            p["id"] = f"p{k}"
        self.places = places
        self.place_by_id = {p["id"]: p for p in places}

    def list_places(self):
        return [{"id": p["id"], "name": p["name"], "hint": p["hint"], "routes": p["routes"],
                 "lat": round(p["lat"], 6), "lon": round(p["lon"], 6)} for p in self.places if p["routes"] > 0]

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _tokens(s):
        return [t for t in re.split(r"[^a-z0-9]+", s.lower()) if t]

    def resolve(self, q: str):
        """A place id ('p12'), '28.66,77.22', or a place / stop name -> (lat, lon, label)."""
        q = q.strip()
        if q in self.place_by_id:
            p = self.place_by_id[q]
            return p["lat"], p["lon"], p["name"] + (f" ({p['hint']})" if p["hint"] else "")
        m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", q)
        if m:
            return float(m.group(1)), float(m.group(2)), "Pinned location"
        for p in self.places:                      # exact name: busiest place with that name
            if p["name"].lower() == q.lower():
                return p["lat"], p["lon"], p["name"]
        want = set(self._tokens(q))
        if not want:
            raise ValueError("empty location")
        best, best_score = None, 0.0
        for i, toks in enumerate(self._name_tokens):
            if not toks:
                continue
            hit = len(want & toks)
            if hit == 0:
                continue
            score = hit / len(want) + 0.2 * hit / len(toks) + 0.01 * min(len(self.stop_routes[i]), 20)
            if score > best_score:
                best, best_score = i, score
        if best is None or best_score < 0.5:
            raise ValueError(f"no stop matches '{q}'")
        return float(self.stop_lat[best]), float(self.stop_lon[best]), str(self.stop_name[best])

    def search_stops(self, q: str, limit=10):
        want = set(self._tokens(q))
        out = []
        for i, toks in enumerate(self._name_tokens):
            hit = len(want & toks)
            if hit:
                out.append((hit / len(want) + 0.2 * hit / len(toks) + 0.01 * min(len(self.stop_routes[i]), 20), i))
        out.sort(reverse=True)
        seen, res = set(), []
        for _, i in out:
            if self.stop_name[i] in seen:
                continue
            seen.add(self.stop_name[i])
            res.append({"stop_id": self.stop_ids[i], "name": self.stop_name[i],
                        "lat": float(self.stop_lat[i]), "lon": float(self.stop_lon[i])})
            if len(res) >= limit:
                break
        return res

    def seg_time(self, seg, dtype, t):
        h = int(t // 3600) % 24
        if seg < 0:
            return None
        return float(self.est[seg, dtype, h])

    def wait_time(self, r, dtype, t):
        n = self.freq[r, dtype, int(t // 3600) % 24]
        if n <= 0:
            return None                      # route not running this hour
        return min(3600.0 / n / 2, MAX_WAIT_S)

    def ride(self, r, a, b, dtype, t, which="est"):
        """Time on route r from position a to b, starting at t. Returns (seconds, levels)."""
        _, st, segs = self.routes[r]
        tt, levels = t, []
        for p in range(a, b):
            s = segs[p]
            if s < 0:   # stretch missing from the model: fall back to citywide speed
                d = np.hypot(*(self.stop_xy[st[p + 1]] - self.stop_xy[st[p]]))
                tt += max(d, 20) / self.city[dtype, int(tt // 3600) % 24]
                levels.append(4)
                continue
            h = int(tt // 3600) % 24
            v = self.est[s, dtype, h]
            if which == "p85":
                q = self.p85[s, dtype, h]
                v = q if np.isfinite(q) and q > v else v * 1.25
            elif which == "sched":
                q = self.sched.get((self.stop_ids[st[p]], self.stop_ids[st[p + 1]], h))
                v = q if q is not None else v
            tt += float(v)
            levels.append(int(self.level[s, dtype, h]))
        return tt - t, levels

    # ------------------------------------------------------------------ search
    def _raptor(self, o_xy, d_xy, t0, dtype, banned=frozenset()):
        S = len(self.stop_ids)
        INF = math.inf
        best = np.full(S, INF)
        tau = [np.full(S, INF) for _ in range(MAX_ROUNDS + 1)]
        parent = [dict() for _ in range(MAX_ROUNDS + 1)]

        acc = self.tree.query_ball_point(o_xy, MAX_ACCESS_M)
        for s in acc:
            t = t0 + walk_s(np.hypot(*(self.stop_xy[s] - o_xy)))
            tau[0][s] = best[s] = t
            parent[0][s] = ("access",)
        egress = {s: walk_s(np.hypot(*(self.stop_xy[s] - d_xy))) for s in self.tree.query_ball_point(d_xy, MAX_ACCESS_M)}
        target = INF
        marked = set(acc)

        for k in range(1, MAX_ROUNDS + 1):
            # routes to scan, each from its earliest marked stop
            q = {}
            for s in marked:
                for r, pos in self.stop_routes[s]:
                    if r in banned:
                        continue
                    if r not in q or pos < q[r]:
                        q[r] = pos
            new_marked = set()
            penalty = TRANSFER_PENALTY_S if k > 1 else 0
            for r, p0 in q.items():
                _, st, segs = self.routes[r]
                t_cur, board = None, None
                for p in range(p0, len(st)):
                    s = st[p]
                    if t_cur is not None and t_cur < min(best[s], target):
                        tau[k][s] = best[s] = t_cur
                        parent[k][s] = ("ride", r, board[0], p, board[1], board[2])
                        new_marked.add(s)
                    prev = tau[k - 1][s]
                    if prev < INF and p < len(st) - 1:
                        w = self.wait_time(r, dtype, prev)
                        if w is not None:
                            tb = prev + w + penalty
                            if t_cur is None or tb < t_cur:
                                t_cur, board = tb, (p, prev, w)
                    if t_cur is not None and p < len(st) - 1:
                        seg = segs[p]
                        v = self.seg_time(seg, dtype, t_cur)
                        if v is None:
                            d = np.hypot(*(self.stop_xy[st[p + 1]] - self.stop_xy[s]))
                            v = max(d, 20) / self.city[dtype, int(t_cur // 3600) % 24]
                        t_cur += v
            # walking transfers
            rides = {s: (tau[k][s], parent[k][s]) for s in new_marked}   # snapshot: walks start from a bus arrival
            for s, (ts, ps) in rides.items():
                for s2, w in self.foot[s]:
                    t = ts + w
                    if t < min(best[s2], target):
                        tau[k][s2] = best[s2] = t
                        parent[k][s2] = ("walk", s, ts, ps)
                        new_marked.add(s2)
            for s, w in egress.items():
                target = min(target, tau[k][s] + w)
            marked = new_marked
            if not marked:
                break
        return tau, parent, egress

    def _rebuild(self, tau, parent, k, s):
        """Walk parent pointers back from stop s in round k."""
        steps = []
        while k > 0:
            p = parent[k][s]
            if p[0] == "walk":
                steps.append(("walk", p[1], s, p[2], tau[k][s]))
                s, p = p[1], p[3]
            r, a, b, t_arr_board, w = p[1], p[2], p[3], p[4], p[5]
            steps.append(("ride", r, a, b, t_arr_board, w))
            s = self.routes[r][1][a]
            k -= 1
        steps.reverse()
        return steps, s

    def plan(self, origin: str, dest: str, depart: datetime, n_options=3):
        olat, olon, oname = self.resolve(origin)
        dlat, dlon, dname = self.resolve(dest)
        o_xy = np.array(to_xy(olat, olon))
        d_xy = np.array(to_xy(dlat, dlon))
        dtype = daytype(depart.date().isoformat())
        t0 = depart.hour * 3600 + depart.minute * 60 + depart.second

        options, banned, seen = [], set(), set()
        for _ in range(n_options + 2):
            tau, parent, egress = self._raptor(o_xy, d_xy, t0, dtype, frozenset(banned))
            found = []
            for k in range(1, MAX_ROUNDS + 1):
                cand = [(tau[k][s] + w, s) for s, w in egress.items() if tau[k][s] < math.inf]
                if cand:
                    arr, s = min(cand)
                    found.append((arr, k, s))
            # keep only options that beat every option with fewer changes
            prev_best = math.inf
            for arr, k, s in sorted(found, key=lambda x: x[1]):
                if arr < prev_best - 60:
                    prev_best = arr
                    steps, first = self._rebuild(tau, parent, k, s)
                    sig = tuple(self.routes[st[1]][0] for st in steps if st[0] == "ride")
                    if sig not in seen:
                        seen.add(sig)
                        options.append(self._describe(steps, first, s, o_xy, d_xy, olat, olon, oname,
                                                      dlat, dlon, dname, t0, dtype, egress[s]))
            if not found:
                break
            # next pass: ban the first bus of the best journey found so far to get a real alternative
            best_opt = min(found)[2]
            steps, _ = self._rebuild(tau, parent, min(found)[1], best_opt)
            banned.add(steps[0][1] if steps[0][0] == "ride" else steps[1][1])
            if len(options) >= n_options + 2:
                break

        direct_m = float(np.hypot(*(d_xy - o_xy)))
        if direct_m < 2500:
            ws = walk_s(direct_m)
            options.append({"summary": "Walk", "depart": _fmt(t0), "arrive": _fmt(t0 + ws),
                            "total_min": round(ws / 60, 1), "legs": [{"type": "walk", "minutes": round(ws / 60, 1),
                            "distance_m": round(direct_m * WALK_DETOUR), "from": oname, "to": dname,
                            "path": [[olat, olon], [dlat, dlon]]}], "transfers": 0})
        options.sort(key=lambda o: o["total_min"])
        return _py({"from": {"query": origin, "name": oname, "lat": olat, "lon": olon},
                "to": {"query": dest, "name": dname, "lat": dlat, "lon": dlon},
                "depart": depart.isoformat(timespec="minutes"),
                "day_type": ["weekday", "saturday", "sunday/holiday"][dtype],
                "options": options[:n_options]})

    def _describe(self, steps, first, last, o_xy, d_xy, olat, olon, oname, dlat, dlon, dname, t0, dtype, egress_s):
        legs = []
        acc_s = walk_s(np.hypot(*(self.stop_xy[first] - o_xy)))
        legs.append({"type": "walk", "from": oname, "to": self.stop_name[first], "minutes": round(acc_s / 60, 1),
                     "distance_m": round(np.hypot(*(self.stop_xy[first] - o_xy)) * WALK_DETOUR),
                     "path": [[olat, olon], [float(self.stop_lat[first]), float(self.stop_lon[first])]]})
        t = t0 + acc_s
        rides = []
        for st in steps:
            if st[0] == "walk":
                a, b = st[1], st[2]
                ws = walk_s(np.hypot(*(self.stop_xy[b] - self.stop_xy[a])))
                legs.append({"type": "walk", "from": self.stop_name[a], "to": self.stop_name[b],
                             "minutes": round(ws / 60, 1), "distance_m": round(np.hypot(*(self.stop_xy[b] - self.stop_xy[a])) * WALK_DETOUR),
                             "path": [[float(self.stop_lat[a]), float(self.stop_lon[a])], [float(self.stop_lat[b]), float(self.stop_lon[b])]]})
                t += ws
                continue
            _, r, a, b, _, _ = st
            rid, stops_r, _ = self.routes[r]
            w = self.wait_time(r, dtype, t) or 0.0
            board_t = t + w
            ride_s, levels = self.ride(r, a, b, dtype, board_t)
            ride_p85, _ = self.ride(r, a, b, dtype, board_t, "p85")
            sched_s, _ = self.ride(r, a, b, dtype, board_t, "sched")
            prof = {}
            for h in range(5, 24):
                v, _ = self.ride(r, a, b, dtype, h * 3600 + 1800)
                prof[h] = v
            rides.append((r, a, b, prof))
            seq = stops_r[a:b + 1]
            legs.append({
                "type": "bus", "route_id": rid, "route": self.route_name.get(rid, rid),
                "route_desc": self.route_desc.get(rid, ""),
                "board_stop": self.stop_name[stops_r[a]], "board_stop_id": self.stop_ids[stops_r[a]],
                "alight_stop": self.stop_name[stops_r[b]], "alight_stop_id": self.stop_ids[stops_r[b]],
                "board_time": _fmt(board_t), "alight_time": _fmt(board_t + ride_s),
                "wait_minutes": round(w / 60, 1), "ride_minutes": round(ride_s / 60, 1),
                "ride_minutes_bad_day": round(ride_p85 / 60, 1), "ride_minutes_timetable": round(sched_s / 60, 1),
                "n_stops": int(b - a),
                "data_quality": {f"L{L}": round(levels.count(L) / max(len(levels), 1), 2) for L in (1, 2, 3, 4)},
                "stops": [{"name": self.stop_name[s], "lat": float(self.stop_lat[s]), "lon": float(self.stop_lon[s])} for s in seq],
                "path": self._path(r, a, b),
            })
            t = board_t + ride_s
        egress_m = float(np.hypot(*(self.stop_xy[last] - d_xy)))
        legs.append({"type": "walk", "from": self.stop_name[last], "to": dname, "minutes": round(egress_s / 60, 1),
                     "distance_m": round(egress_m * WALK_DETOUR),
                     "path": [[float(self.stop_lat[last]), float(self.stop_lon[last])], [dlat, dlon]]})
        t += egress_s
        total = t - t0

        # same journey at every hour of the day: shows the effect of traffic
        walk_total = sum(l["minutes"] for l in legs if l["type"] == "walk") * 60
        wait_total = sum(l["wait_minutes"] for l in legs if l["type"] == "bus") * 60
        profile = {h: round((walk_total + wait_total + sum(p[3][h] for p in rides)) / 60, 1) for h in range(5, 24)}
        quiet_h = min(profile, key=profile.get)
        bus_legs = [l for l in legs if l["type"] == "bus"]
        return {
            "summary": " → ".join(l["route"] for l in bus_legs),
            "depart": _fmt(t0), "arrive": _fmt(t), "total_min": round(total / 60, 1),
            "total_min_bad_day": round((total + sum((l["ride_minutes_bad_day"] - l["ride_minutes"]) * 60 for l in bus_legs)) / 60, 1),
            "total_min_timetable": round((total + sum((l["ride_minutes_timetable"] - l["ride_minutes"]) * 60 for l in bus_legs)) / 60, 1),
            "transfers": len(bus_legs) - 1,
            "walk_min": round(walk_total / 60, 1), "wait_min": round(wait_total / 60, 1),
            "in_bus_min": round(sum(l["ride_minutes"] for l in bus_legs), 1),
            "quiet_hour": {"hour": f"{quiet_h:02d}:30", "total_min": profile[quiet_h]},
            "by_hour": profile,
            "legs": legs,
        }

    def seg_geometry(self):
        """Road-following polyline for every model stretch (for the traffic map)."""
        if getattr(self, "_seg_geom", None) is None:
            self._path(0, 0, 0)  # loads route lines
            from geo import LAT0, LON0, M_PER_DEG_LAT, M_PER_DEG_LON
            geom = {}
            for r, (rid, st, segs) in enumerate(self.routes):
                g = self.route_line.get(rid)
                if g is None:
                    continue
                ch, xs, ys = g.chain_m.values, g.x.values, g.y.values
                c = self.route_chain[rid]
                for p, s in enumerate(segs):
                    if s < 0 or s in geom:
                        continue
                    i0, i1 = np.searchsorted(ch, [c[p], c[p + 1]])
                    idx = np.unique(np.r_[np.arange(i0, i1, 4), min(i1, len(ch) - 1)])
                    if len(idx) < 2:
                        continue
                    geom[s] = [[round(float(y / M_PER_DEG_LAT + LAT0), 5), round(float(x / M_PER_DEG_LON + LON0), 5)]
                               for x, y in zip(xs[idx], ys[idx])]
            self._seg_geom = geom
        return self._seg_geom

    def _path(self, r, a, b):
        if self.route_line is None:
            rl = pd.read_parquet(config.MODEL / "route_line.parquet")
            self.route_line = {k: g for k, g in rl.groupby("route_id")}
            rs = pd.read_parquet(config.MODEL / "route_stops.parquet")
            self.route_chain = {k: g.sort_values("seq").chain_m.values for k, g in rs.groupby("route_id")}
        rid = self.routes[r][0]
        g = self.route_line[rid]
        c = self.route_chain[rid]
        sel = g[(g.chain_m >= c[a]) & (g.chain_m <= c[b])].iloc[::5]
        x, y = sel.x.values.astype(float), sel.y.values.astype(float)
        from geo import LAT0, LON0, M_PER_DEG_LAT, M_PER_DEG_LON
        lat = y / M_PER_DEG_LAT + LAT0
        lon = x / M_PER_DEG_LON + LON0
        return [[round(a_, 6), round(b_, 6)] for a_, b_ in zip(lat, lon)]


def _py(o):
    """Convert numpy numbers to plain Python so the result is valid JSON."""
    if isinstance(o, dict):
        return {str(k): _py(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_py(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return round(float(o), 2)
    if isinstance(o, np.str_):
        return str(o)
    return o


def _fmt(t):
    t = int(round(t)) % 86400
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}"


if __name__ == "__main__":
    import json
    import sys
    import time
    md = sys.argv[1] if len(sys.argv) > 1 else config.MODEL
    t = time.time()
    p = Planner(md)
    print(f"loaded in {time.time() - t:.1f}s")
    for when in ("2026-10-20T08:30", "2026-10-20T23:00"):
        t = time.time()
        res = p.plan("Kashmere Gate ISBT", "Nehru Place", datetime.fromisoformat(when))
        print(f"\n== {when}  ({time.time() - t:.1f}s)  {res['from']['name']} -> {res['to']['name']}")
        for o in res["options"]:
            print(f"  {o['summary']:30s} {o['depart']}→{o['arrive']} {o['total_min']} min "
                  f"(walk {o.get('walk_min')}, wait {o.get('wait_min')}, bus {o.get('in_bus_min')}) "
                  f"timetable {o.get('total_min_timetable')} bad-day {o.get('total_min_bad_day')} quiet {o.get('quiet_hour')}")
