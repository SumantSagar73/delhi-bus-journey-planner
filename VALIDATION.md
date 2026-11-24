# Validation report

Model built from **4 days** (2026-10-01 to 2026-10-04). Tested on **12,000 real bus rides** from **3 unseen days** (2026-10-05 to 2026-10-20), cut from the GPS data: a bus on a given route, from one stop to another 5–30 stops later, at the time it actually ran.

We compare three predictions of the time on the bus with what actually happened:

- **Our model**: GPS-learned, by stretch of road, day type and hour.
- **Flat model**: the same GPS data, but a single all-day average per stretch. Shows the value of modelling time of day.
- **Timetable**: the official GTFS schedule.

MAE = mean absolute error. MAPE = median absolute % error. Within ±20% = share of rides predicted within 20% of the real time. Bias > 0 means predicting too slow.

## Overall

| method | MAE (min) | MAPE | within ±20% | bias (min) |
|---|---|---|---|---|
| Our model | 2.65 | 11.3% | 73% | -0.95 |
| Flat model (no time of day) | 3.55 | 16.0% | 59% | -0.6 |
| Timetable | 4.66 | 24.9% | 41% | -0.73 |


## By time of day

| time | rides | actual avg (min) | model MAE | model ±20% | timetable MAE | timetable ±20% |
|---|---|---|---|---|---|---|
| 05-08 early | 1873 | 12.5 | 1.56 | 81% | 4.67 | 28% |
| 08-11 morning peak | 2630 | 15.8 | 2.25 | 78% | 3.83 | 49% |
| 11-17 midday | 3933 | 16.5 | 2.9 | 72% | 4.61 | 46% |
| 17-21 evening peak | 2576 | 18.2 | 3.68 | 66% | 5.96 | 38% |
| 21-05 night | 988 | 12.7 | 2.14 | 69% | 3.67 | 41% |


## By ride length

| stops | rides | actual avg (min) | model MAE | model MAPE | timetable MAE | timetable MAPE |
|---|---|---|---|---|---|---|
| 5 | 7311 | 9.6 | 1.97 | 12.3% | 3.3 | 26.5% |
| 10 | 3236 | 18.5 | 2.97 | 10.5% | 5.34 | 23.4% |
| 20 | 1084 | 36.6 | 5.04 | 9.2% | 9.12 | 20.8% |
| 30 | 369 | 52.7 | 6.33 | 7.9% | 12.57 | 20.0% |


## By day type

| day type | rides | MAE (min) | MAPE | within ±20% | bias (min) |
|---|---|---|---|---|---|
| sunday/holiday | 4000 | 2.16 | 10.1% | 77% | -0.83 |
| weekday | 8000 | 2.9 | 12.0% | 71% | -1.01 |


## Does it follow rush hour? (weekday, average seconds per stop-to-stop hop)

| hour | actual | our model | timetable |
|---|---|---|---|
| 00:00 | 66 | 74 | 94 |
| 01:00 | 65 | 63 | 96 |
| 02:00 | 80 | 82 | 111 |
| 03:00 | 64 | 59 | 86 |
| 04:00 | 63 | 66 | 93 |
| 05:00 | 78 | 76 | 111 |
| 06:00 | 84 | 83 | 108 |
| 07:00 | 97 | 92 | 108 |
| 08:00 | 111 | 106 | 109 |
| 09:00 | 117 | 111 | 103 |
| 10:00 | 123 | 115 | 106 |
| 11:00 | 128 | 118 | 107 |
| 12:00 | 128 | 118 | 107 |
| 13:00 | 124 | 114 | 107 |
| 14:00 | 125 | 115 | 107 |
| 15:00 | 130 | 116 | 109 |
| 16:00 | 135 | 124 | 111 |
| 17:00 | 137 | 127 | 109 |
| 18:00 | 153 | 138 | 105 |
| 19:00 | 159 | 139 | 107 |
| 20:00 | 130 | 124 | 109 |
| 21:00 | 105 | 106 | 107 |
| 22:00 | 91 | 93 | 106 |
| 23:00 | 84 | 84 | 110 |


## Comparison with Google Maps (door to door, weekday)

_Google Maps column not filled in yet: see validation/google_maps_comparison.csv._

| from | to | weekday_depart | our_total_min | our_routes | timetable_total_min | google_maps_total_min |
|---|---|---|---|---|---|---|
| ISBT Kashmere Gate | Nehru Place | 08:30 | 63.0 | 214DOWN → 425UP | 60.5 | nan |
| ISBT Kashmere Gate | Nehru Place | 13:00 | 72.7 | BYPASS EXPRESS DOWN → 534AUP | 75.8 | nan |
| ISBT Kashmere Gate | Nehru Place | 18:30 | 78.0 | 706UP → 425UP | 75.2 | nan |
| ISBT Kashmere Gate | Nehru Place | 22:30 | 60.9 | 348UP → 425UP | 65.2 | nan |
| Anand Vihar ISBT | Dhaula Kuan | 08:30 | 74.6 | 73UP → 740EXTUP | 69.7 | nan |
| Anand Vihar ISBT | Dhaula Kuan | 13:00 | 83.7 | 73UP → 740EXTUP | 70.3 | nan |
| Anand Vihar ISBT | Dhaula Kuan | 18:30 | 88.5 | 73UP → 706UP | 69.1 | nan |
| Anand Vihar ISBT | Dhaula Kuan | 22:30 | 62.2 | 73UP → 740EXTUP | 68.3 | nan |
| Dwarka Sector 1 | AIIMS | 08:30 | 56.6 | 764UP → 543ADOWN | 62.6 | nan |
| Dwarka Sector 1 | AIIMS | 13:00 | 57.0 | 764UP → 543ADOWN | 62.5 | nan |
| Dwarka Sector 1 | AIIMS | 18:30 | 60.9 | 764UP → 543ADOWN | 63.1 | nan |
| Dwarka Sector 1 | AIIMS | 22:30 | 43.4 | 764UP → 543ADOWN | 63.1 | nan |
| Jahangirpuri Metro Station GT Road | ISBT Kashmere Gate | 08:30 | 32.9 | 103DOWN | 36.0 | nan |
| Jahangirpuri Metro Station GT Road | ISBT Kashmere Gate | 13:00 | 40.5 | 103DOWN | 36.2 | nan |
| Jahangirpuri Metro Station GT Road | ISBT Kashmere Gate | 18:30 | 47.6 | 137DOWN | 39.7 | nan |
| Jahangirpuri Metro Station GT Road | ISBT Kashmere Gate | 22:30 | 29.8 | 103DOWN | 34.1 | nan |
| Nehru Place | Shivaji Stadium Terminal ( Connaught Place ) | 08:30 | 42.9 | 425DOWN → 966UP | 48.9 | nan |
| Nehru Place | Shivaji Stadium Terminal ( Connaught Place ) | 13:00 | 58.2 | 425DOWN → 966UP | 56.8 | nan |
| Nehru Place | Shivaji Stadium Terminal ( Connaught Place ) | 18:30 | 61.4 | 425DOWN → 966UP | 49.2 | nan |
| Nehru Place | Shivaji Stadium Terminal ( Connaught Place ) | 22:30 | 42.2 | 425DOWN → 966UP | 50.0 | nan |
| Mehrauli Terminal | ISBT Sarai Kale Khan | 08:30 | 55.9 | 413DOWN → 711UP | 53.1 | nan |
| Mehrauli Terminal | ISBT Sarai Kale Khan | 13:00 | 71.9 | 534DOWN | 53.9 | nan |
| Mehrauli Terminal | ISBT Sarai Kale Khan | 18:30 | 78.9 | 534DOWN | 54.2 | nan |
| Mehrauli Terminal | ISBT Sarai Kale Khan | 22:30 | 56.1 | 534DOWN | 54.9 | nan |
| Rohini Sec 22 Terminal | Azadpur Terminal | 08:30 | 60.2 | 114ADOWN | 59.3 | nan |
| Rohini Sec 22 Terminal | Azadpur Terminal | 13:00 | 65.4 | 114ADOWN | 59.6 | nan |
| Rohini Sec 22 Terminal | Azadpur Terminal | 18:30 | 69.8 | 114ADOWN | 59.8 | nan |
| Rohini Sec 22 Terminal | Azadpur Terminal | 22:30 | 54.3 | 114ADOWN | 62.3 | nan |
| Badarpur Border (T) | ITO Ring Road | 08:30 | 61.0 | 473DOWN → 261UP | 68.5 | nan |
| Badarpur Border (T) | ITO Ring Road | 13:00 | 65.2 | 405DOWN → 623DOWN | 63.1 | nan |
| Badarpur Border (T) | ITO Ring Road | 18:30 | 79.0 | 473DOWN → BYPASS EXPRESS UP | 69.4 | nan |
| Badarpur Border (T) | ITO Ring Road | 22:30 | 54.2 | 405DOWN | 67.7 | nan |
| Uttam Nagar Terminal | Rajouri Garden | 08:30 | 26.3 | 861AUP | 25.1 | nan |
| Uttam Nagar Terminal | Rajouri Garden | 13:00 | 31.0 | 861AUP | 26.1 | nan |
| Uttam Nagar Terminal | Rajouri Garden | 18:30 | 37.3 | 861AUP | 27.8 | nan |
| Uttam Nagar Terminal | Rajouri Garden | 22:30 | 26.5 | 861AUP | 25.6 | nan |
| Mayur Vihar Phase III (T) Paper Market | Lajpat Nagar | 08:30 | 63.5 | D-032DOWN | 60.5 | nan |
| Mayur Vihar Phase III (T) Paper Market | Lajpat Nagar | 13:00 | 64.4 | D-032DOWN | 63.0 | nan |
| Mayur Vihar Phase III (T) Paper Market | Lajpat Nagar | 18:30 | 70.4 | 611UP | 63.0 | nan |
| Mayur Vihar Phase III (T) Paper Market | Lajpat Nagar | 22:30 | 47.5 | 211BSTL-HPDDOWN → 543AUP | 61.9 | nan |


Google Maps times are looked up by hand in Google Maps (public transport, bus only, same weekday and departure time) and typed into `validation/google_maps_comparison.csv`; re-running `validate.py` updates this section.
