# Validation report

Model built from **24 days** (2026-10-01 to 2026-10-24). Tested on **28,000 real bus rides** from **7 unseen days** (2026-10-25 to 2026-10-31), cut from the GPS data: a bus on a given route, from one stop to another 5–30 stops later, at the time it actually ran.

We compare three predictions of the time on the bus with what actually happened:

- **Our model**: GPS-learned, by stretch of road, day type and hour.
- **Flat model**: the same GPS data, but a single all-day average per stretch. Shows the value of modelling time of day.
- **Timetable**: the official GTFS schedule.

MAE = mean absolute error. MAPE = median absolute % error. Within ±20% = share of rides predicted within 20% of the real time. Bias > 0 means predicting too slow.

## Overall

| method | MAE (min) | MAPE | within ±20% | bias (min) |
|---|---|---|---|---|
| Our model | 2.73 | 11.5% | 72% | -1.0 |
| Flat model (no time of day) | 3.85 | 17.4% | 55% | -0.61 |
| Timetable | 4.81 | 25.2% | 41% | -1.43 |


### Key findings

- **Our model's average error is 2.73 min vs 4.81 min for the timetable**
  (43% lower), and it gets 72% of rides within ±20%
  against 41% for the timetable.
- **Time of day matters.** The same GPS data without time of day (flat model) has 3.85 min error, so about
  54% of our gain over the
  timetable comes from modelling the hour of day; the rest from using measured rather than scheduled speeds.
- **The timetable is flat; real traffic isn't.** The timetable assumes about the same time per stop all day. Real
  buses on weekdays are roughly twice as slow at 6 pm as at 5 am, and the model tracks that curve (table below).
- **Honest weakness: a trend the history can't see.** The test week (2026-10-25 to 2026-10-31, the run-up
  to Diwali) was slower than the training weeks. On weekday evenings (17–21 h) the model predicts
  93% of the real time, i.e. it is 7% optimistic. Recency weighting of
  history and the live-data correction (TECHNICAL_NOTE.md §5) are designed for exactly this.


## By time of day

| time | rides | actual avg (min) | model MAE | model ±20% | timetable MAE | timetable ±20% |
|---|---|---|---|---|---|---|
| 05-08 early | 4369 | 12.1 | 1.51 | 81% | 4.21 | 28% |
| 08-11 morning peak | 6454 | 15.8 | 2.27 | 78% | 3.81 | 51% |
| 11-17 midday | 9033 | 16.8 | 3.05 | 69% | 4.94 | 43% |
| 17-21 evening peak | 5858 | 18.8 | 3.92 | 64% | 6.56 | 34% |
| 21-05 night | 2286 | 13.5 | 2.1 | 73% | 3.81 | 42% |


## By ride length

| stops | rides | actual avg (min) | model MAE | model MAPE | timetable MAE | timetable MAPE |
|---|---|---|---|---|---|---|
| 5 | 17600 | 10.0 | 2.0 | 12.4% | 3.46 | 26.9% |
| 10 | 7319 | 19.4 | 3.21 | 10.6% | 5.74 | 23.5% |
| 20 | 2279 | 37.0 | 5.15 | 9.5% | 9.31 | 21.5% |
| 30 | 802 | 56.1 | 7.56 | 8.9% | 13.24 | 18.6% |


## By day type

| day type | rides | MAE (min) | MAPE | within ±20% | bias (min) |
|---|---|---|---|---|---|
| saturday | 4000 | 3.34 | 12.3% | 70% | -2.28 |
| sunday/holiday | 4000 | 2.7 | 10.4% | 76% | -1.82 |
| weekday | 20000 | 2.62 | 11.6% | 72% | -0.58 |


## Does it follow rush hour? (weekday, average seconds per stop-to-stop hop)

| hour | actual | our model | timetable |
|---|---|---|---|
| 00:00 | 73 | 75 | 101 |
| 01:00 | 64 | 59 | 96 |
| 02:00 | 73 | 59 | 96 |
| 03:00 | 72 | 71 | 105 |
| 04:00 | 72 | 72 | 105 |
| 05:00 | 74 | 75 | 106 |
| 06:00 | 81 | 82 | 107 |
| 07:00 | 90 | 92 | 106 |
| 08:00 | 104 | 104 | 106 |
| 09:00 | 118 | 113 | 106 |
| 10:00 | 120 | 114 | 106 |
| 11:00 | 124 | 119 | 106 |
| 12:00 | 124 | 121 | 107 |
| 13:00 | 122 | 117 | 106 |
| 14:00 | 125 | 120 | 107 |
| 15:00 | 131 | 120 | 107 |
| 16:00 | 129 | 121 | 109 |
| 17:00 | 144 | 130 | 106 |
| 18:00 | 160 | 143 | 105 |
| 19:00 | 148 | 138 | 109 |
| 20:00 | 125 | 120 | 107 |
| 21:00 | 109 | 105 | 107 |
| 22:00 | 93 | 91 | 109 |
| 23:00 | 79 | 81 | 106 |


## Comparison with Google Maps (door to door, weekday)

_Google Maps column not filled in yet: see validation/google_maps_comparison.csv._

| from | to | weekday_depart | our_total_min | our_routes | timetable_total_min | google_maps_total_min |
|---|---|---|---|---|---|---|
| ISBT Kashmere Gate | Nehru Place | 08:30 | 62.8 | 214DOWN → 425UP | 59.1 | nan |
| ISBT Kashmere Gate | Nehru Place | 13:00 | 76.9 | 706UP → 425UP | 75.7 | nan |
| ISBT Kashmere Gate | Nehru Place | 18:30 | 78.9 | 706UP → 425UP | 73.4 | nan |
| ISBT Kashmere Gate | Nehru Place | 22:30 | 61.1 | 214DOWN → 425UP | 66.4 | nan |
| Anand Vihar ISBT | Dhaula Kuan | 08:30 | 78.7 | 73UP → 729UP | 70.6 | nan |
| Anand Vihar ISBT | Dhaula Kuan | 13:00 | 84.0 | 73UP → 740EXTUP | 69.8 | nan |
| Anand Vihar ISBT | Dhaula Kuan | 18:30 | 93.2 | 73UP → 706UP | 70.2 | nan |
| Anand Vihar ISBT | Dhaula Kuan | 22:30 | 58.2 | 73UP → 740EXTUP | 67.8 | nan |
| Dwarka Sector 1 | AIIMS | 08:30 | 63.0 | 764UP → 543ADOWN | 63.7 | nan |
| Dwarka Sector 1 | AIIMS | 13:00 | 60.6 | 764UP → 543ADOWN | 62.5 | nan |
| Dwarka Sector 1 | AIIMS | 18:30 | 57.4 | 764UP → 543ADOWN | 62.8 | nan |
| Dwarka Sector 1 | AIIMS | 22:30 | 45.5 | 764UP → 543ADOWN | 63.5 | nan |
| Jahangirpuri Metro Station GT Road | ISBT Kashmere Gate | 08:30 | 34.1 | 112DOWN | 36.8 | nan |
| Jahangirpuri Metro Station GT Road | ISBT Kashmere Gate | 13:00 | 41.4 | 103DOWN | 36.3 | nan |
| Jahangirpuri Metro Station GT Road | ISBT Kashmere Gate | 18:30 | 44.4 | 112DOWN | 38.4 | nan |
| Jahangirpuri Metro Station GT Road | ISBT Kashmere Gate | 22:30 | 31.1 | 103DOWN | 36.0 | nan |
| Nehru Place | Shivaji Stadium Terminal ( Connaught Place ) | 08:30 | 43.2 | 425DOWN → 966UP | 48.9 | nan |
| Nehru Place | Shivaji Stadium Terminal ( Connaught Place ) | 13:00 | 60.0 | 425DOWN → 966UP | 56.3 | nan |
| Nehru Place | Shivaji Stadium Terminal ( Connaught Place ) | 18:30 | 59.5 | 425DOWN → 966UP | 48.9 | nan |
| Nehru Place | Shivaji Stadium Terminal ( Connaught Place ) | 22:30 | 42.2 | 440DOWN → 522UP | 48.8 | nan |
| Mehrauli Terminal | ISBT Sarai Kale Khan | 08:30 | 57.2 | 413DOWN → 711UP | 53.1 | nan |
| Mehrauli Terminal | ISBT Sarai Kale Khan | 13:00 | 74.7 | 534DOWN | 53.7 | nan |
| Mehrauli Terminal | ISBT Sarai Kale Khan | 18:30 | 89.2 | 534DOWN | 53.5 | nan |
| Mehrauli Terminal | ISBT Sarai Kale Khan | 22:30 | 54.1 | 534DOWN | 54.3 | nan |
| Rohini Sec 22 Terminal | Azadpur Terminal | 08:30 | 60.6 | 114ADOWN | 59.2 | nan |
| Rohini Sec 22 Terminal | Azadpur Terminal | 13:00 | 70.5 | 114ADOWN | 60.1 | nan |
| Rohini Sec 22 Terminal | Azadpur Terminal | 18:30 | 74.2 | 114ADOWN | 59.5 | nan |
| Rohini Sec 22 Terminal | Azadpur Terminal | 22:30 | 53.8 | 114ADOWN | 62.4 | nan |
| Badarpur Border (T) | ITO Ring Road | 08:30 | 62.1 | 405DOWN → 623DOWN | 65.0 | nan |
| Badarpur Border (T) | ITO Ring Road | 13:00 | 64.2 | 405DOWN → 623DOWN | 63.6 | nan |
| Badarpur Border (T) | ITO Ring Road | 18:30 | 76.8 | 405DOWN | 73.3 | nan |
| Badarpur Border (T) | ITO Ring Road | 22:30 | 53.5 | 405DOWN | 67.9 | nan |
| Uttam Nagar Terminal | Rajouri Garden | 08:30 | 26.6 | 861AUP | 25.3 | nan |
| Uttam Nagar Terminal | Rajouri Garden | 13:00 | 31.4 | 861AUP | 25.0 | nan |
| Uttam Nagar Terminal | Rajouri Garden | 18:30 | 39.8 | 861AUP | 25.6 | nan |
| Uttam Nagar Terminal | Rajouri Garden | 22:30 | 26.7 | 861AUP | 25.6 | nan |
| Mayur Vihar Phase III (T) Paper Market | Lajpat Nagar | 08:30 | 68.2 | D-032DOWN | 60.6 | nan |
| Mayur Vihar Phase III (T) Paper Market | Lajpat Nagar | 13:00 | 71.1 | D-032DOWN | 66.7 | nan |
| Mayur Vihar Phase III (T) Paper Market | Lajpat Nagar | 18:30 | 71.4 | D-4403UP → 543AUP | 74.0 | nan |
| Mayur Vihar Phase III (T) Paper Market | Lajpat Nagar | 22:30 | 51.5 | 611ESTLDOWN → 543AUP | 64.8 | nan |


Google Maps times are looked up by hand in Google Maps (public transport, bus only, same weekday and departure time) and typed into `validation/google_maps_comparison.csv`; re-running `validate.py` updates this section.
