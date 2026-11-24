"""Records the demo video by driving the running app in Chrome, with on-screen captions.

Needs the app running on http://localhost:8000. Usage:
  ../.venv/bin/python record_demo.py        ->  demo/demo.mp4
"""
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
URL = "http://localhost:8000"
W, H = 1440, 900

CSS = """
#cap{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:99999;max-width:80%;
  background:rgba(16,24,40,.88);color:#fff;font:600 22px/1.35 system-ui,Segoe UI,Roboto,sans-serif;
  padding:14px 22px;border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.3);text-align:center;
  transition:opacity .35s;opacity:0;pointer-events:none}
#cap small{display:block;font-weight:400;font-size:16px;opacity:.8;margin-top:4px}
#slide{position:fixed;inset:0;z-index:99998;background:#0b3b39;color:#fff;display:flex;flex-direction:column;
  align-items:center;justify-content:center;font-family:system-ui,Segoe UI,Roboto,sans-serif;transition:opacity .5s;opacity:0;display:none;pointer-events:none}
#slide h1{font-size:54px;margin:0 0 12px;letter-spacing:-.02em} #slide p{font-size:24px;margin:6px;opacity:.9}
#slide table{border-collapse:collapse;margin-top:24px;font-size:26px} #slide td,#slide th{padding:12px 26px;border-bottom:1px solid #ffffff33;text-align:left}
#slide .hl{color:#7ee2d6;font-weight:800}
.flash{outline:4px solid #f79009 !important;outline-offset:3px;border-radius:10px;transition:outline .2s}
"""


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(HERE / "raw"),
                                  record_video_size={"width": W, "height": H}, device_scale_factor=1)
        page = ctx.new_page()
        page.goto(URL)
        page.wait_for_selector("#go")
        page.add_style_tag(content=CSS)
        page.evaluate("""() => { const c=document.createElement('div'); c.id='cap'; document.body.appendChild(c);
                                 const s=document.createElement('div'); s.id='slide'; document.body.appendChild(s); }""")
        page.wait_for_timeout(1500)

        def cap(text, sub="", hold=3.5):
            page.evaluate("([t,s]) => { const c=document.getElementById('cap'); c.innerHTML=t+(s?'<small>'+s+'</small>':''); c.style.opacity=1; }", [text, sub])
            page.wait_for_timeout(int(hold * 1000))

        def nocap():
            page.evaluate("() => document.getElementById('cap').style.opacity=0")
            page.wait_for_timeout(400)

        def slide(html, hold):
            page.evaluate("h => { const s=document.getElementById('slide'); s.innerHTML=h; s.style.display='flex'; s.style.opacity=1; }", html)
            page.wait_for_timeout(int(hold * 1000))
            page.evaluate("() => { const s=document.getElementById('slide'); s.style.opacity=0; setTimeout(()=>s.style.display='none',500); }")
            page.wait_for_timeout(600)

        def flash(sel, ms=900):
            page.evaluate("s => document.querySelector(s)?.classList.add('flash')", sel)
            page.wait_for_timeout(ms)
            page.evaluate("s => document.querySelector(s)?.classList.remove('flash')", sel)

        def set_hour(h):
            page.evaluate("h => { const r=document.getElementById('tHour'); r.value=h; r.dispatchEvent(new Event('input')); }", h)

        def choose(field, text):
            inp = page.locator(f"#f-{field} input")
            inp.click()
            page.wait_for_timeout(300)
            inp.fill("")
            inp.type(text, delay=90)
            page.wait_for_timeout(900)
            page.keyboard.press("Enter")
            page.wait_for_timeout(600)

        def plan_and_wait():
            flash("#go", 500)
            page.click("#go")
            page.wait_for_selector(".card", timeout=60000)
            page.wait_for_timeout(1500)

        # 1. title
        slide("<h1>Delhi Buses as Traffic Sensors</h1><p>Bus travel times learned from GPS, and a journey planner</p>"
              "<p style='opacity:.7;font-size:18px;margin-top:22px'>Transport Stack Hackathon 2026 · Problem 1</p>", 4.5)

        # 2. the problem
        slide("<h1 style='font-size:40px'>The timetable says every hour is the same</h1>"
              "<p>Delhi's bus timetable assumes ~106 seconds per stop, all day.</p>"
              "<p>Real buses: <span class='hl'>76 s at 5 am</span> and <span class='hl'>158 s at 6 pm</span>.</p>"
              "<p style='margin-top:20px'>We used 6,000+ DTC buses as moving traffic sensors:</p>"
              "<p><span class='hl'>550M+ GPS reports → 38.4 million stop-to-stop measurements</span> (October 2026)</p>", 7)

        # 3. traffic map
        page.evaluate("() => map.setView([28.62, 77.2], 12)")
        cap("This is what the buses tell us about Delhi's roads", "Traffic map: modelled bus speed on every stretch of road", 2.5)
        page.click(".switch span")
        page.wait_for_timeout(500)
        set_hour(8)
        page.wait_for_timeout(4500)
        cap("Weekday, 8 am", "Green = fast, red = buses crawling", 3)
        for h, txt in [(13, "1 pm"), (18, "6 pm: evening rush")]:
            set_hour(h)
            page.wait_for_timeout(3500)
            cap(f"Weekday, {txt}", "Same roads, different hour", 3)
        set_hour(23)
        page.wait_for_timeout(3500)
        cap("Weekday, 11 pm", "Roads clear again", 2.5)
        page.click(".switch span")
        nocap()

        # 4. plan a trip: morning
        cap("Plan a trip: Kashmere Gate ISBT → Nehru Place", "Pick places from the dropdown, choose day and time", 2.5)
        choose("from", "isbt kashmere gate")
        choose("to", "nehru place")
        page.click("#times .pill[data-t='08:30']")
        page.wait_for_timeout(500)
        plan_and_wait()
        flash(".card", 1200)
        cap("Weekday 8:30 am: the best options, with total time and arrival", "Bus route chips, plus a walk / wait / on-bus breakdown", 4)
        flash(".card .insight", 1500)
        cap("Effect of traffic: how much longer than at a quiet hour", "Plus a bad-day time and what the timetable claims", 4.5)
        cap("The bar chart: this same trip at every hour of the day", "The dark bar is your departure time", 3.5)
        page.evaluate("() => document.querySelector('.card .steps').scrollIntoView({behavior:'smooth', block:'center'})")
        page.wait_for_timeout(1200)
        cap("Step-by-step: where to board, how often the bus comes, where to change and get off",
            "And how much of the ride is timed from real GPS measurements", 5)
        nocap()

        # 5. same trip, evening and night
        page.evaluate("() => document.querySelector('aside').scrollTo({top:0, behavior:'smooth'})")
        page.wait_for_timeout(800)
        page.click("#times .pill[data-t='18:30']")
        plan_and_wait()
        cap("Same trip at 6:30 pm: the evening rush changes the answer", "", 4)
        page.click("#times .pill[data-t='22:30']")
        plan_and_wait()
        cap("And at 10:30 pm: faster roads, but buses come less often", "Waiting time comes from how often buses actually ran", 4)
        nocap()

        # 6. API
        page.goto(URL + "/docs")
        page.add_style_tag(content=CSS)
        page.evaluate("""() => { const c=document.createElement('div'); c.id='cap'; document.body.appendChild(c);
                                 const s=document.createElement('div'); s.id='slide'; document.body.appendChild(s); }""")
        page.wait_for_timeout(1500)
        cap("Everything is also an API: GET /journeys?from=…&to=…&depart=…", "Interactive documentation at /docs", 3)
        page.click("text=/journeys")
        page.wait_for_timeout(1000)
        page.click("text=Try it out")
        page.wait_for_timeout(600)
        page.fill("input[placeholder='from']", "ISBT Kashmere Gate")
        page.fill("input[placeholder='to']", "Nehru Place")
        page.fill("input[placeholder='depart']", "2026-10-27T08:30")
        page.click("button.execute")
        page.wait_for_timeout(5000)
        page.evaluate("() => document.querySelector('.responses-inner')?.scrollIntoView({behavior:'smooth', block:'start'})")
        cap("Returns JSON journey options: legs, stops, times, traffic profile", "Ready for any app to use", 5)
        nocap()

        # 7. results
        slide("<h1 style='font-size:42px'>Does it work?</h1>"
              "<p>Trained on 1–24 Oct · tested on <span class='hl'>28,000 real bus rides</span> from 25–31 Oct it never saw</p>"
              "<table><tr><th></th><th>avg error</th><th>within ±20%</th></tr>"
              "<tr><td class='hl'>Our model</td><td class='hl'>2.7 min</td><td class='hl'>72%</td></tr>"
              "<tr><td>Same data, no time of day</td><td>3.9 min</td><td>55%</td></tr>"
              "<tr><td>Official timetable</td><td>4.8 min</td><td>41%</td></tr></table>"
              "<p style='margin-top:22px'>43% lower error than the timetable</p>", 8)
        slide("<h1 style='font-size:42px'>How it works</h1>"
              "<p>Clean GPS → snap to route → time at every stop → stop-to-stop times</p>"
              "<p>→ model per stretch × day type × hour, with a 4-level fallback for thin data</p>"
              "<p>→ RAPTOR journey planner, up to 2 changes, walking included</p>"
              "<p style='margin-top:22px;opacity:.8'>Next: live GTFS-RT correction · metro legs · next-bus predictions</p>", 7)
        slide("<h1 style='font-size:40px'>github.com/SumantSagar73/<br>delhi-bus-journey-planner</h1>"
              "<p>Code · README · technical note · validation report</p>", 5)

        video = page.video.path()
        ctx.close()
        browser.close()

    out = HERE / "demo.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-c:v", "libx264", "-preset", "medium",
                    "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True)
    print("saved", out)


if __name__ == "__main__":
    t = time.time()
    main()
    print(f"{time.time() - t:.0f}s")
