# SootAble

SootAble is a phone app for a small diesel exhaust meter (target cost about Rs. 500). Once a day the meter takes a smoke
reading on its own and sends it to the phone. The app shows the number against the legal limit, keeps up to 1000 days of
history so slow wear shows up as a trend, and warns the owner while a worn injector or clogged filter is still a small
repair, months before the next PUC test.

Built for C://hacks 2026, App & Web Engineering (Advanced), **UN SDG 13: Climate Action**. Black carbon from badly
maintained diesel engines is a short-lived climate pollutant, and catching a degrading engine early is one of the cheapest
ways to cut it.

<p>
<img src="docs/screenshots/04-home.png" width="190" alt="Home screen">
<img src="docs/screenshots/05-trend.png" width="190" alt="Outlook and trend">
<img src="docs/screenshots/03-find-meter.png" width="190" alt="Pairing a meter">
<img src="docs/screenshots/06-history.png" width="190" alt="History">
</p>

## Try it

There are two things to look at. They are separate: the app needs Python running, the hardware demo is just a web page.

### 1. The hardware demo (nothing to install)

A 3D model of the meter, built from our CAD design. Drag to orbit, change how much smoke is in the exhaust, and watch the
infrared sensor reading, opacity and k change, with the phone's view and the ESP32 serial log beside it.

**Live: https://ayushvyk.github.io/C-Hacks/**

You can also open [hardware/index.html](hardware/index.html) straight from a clone, or start the app and go to
`/hardware/`. The 3D library is bundled in the folder; only the fonts come from the internet.

![Hardware demo](docs/screenshots/07-hardware-demo.png)

### 2. The app

You need Python 3.10 or newer.

```
git clone https://github.com/AyushVyk/C-Hacks.git
cd C-Hacks
python -m venv .venv
.venv\Scripts\activate            # macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Then open **http://127.0.0.1:8000**. It is a phone app, so on a laptop it sits inside a phone-sized frame.

The first run walks through adding a vehicle and finding its meter. There is no physical meter yet, so the search finds
three virtual ones; tap **No meter? Use demo data** to load a few months of example readings instead (a healthy engine or
one that is wearing out). Everything is stored locally in `data/sootable.db`; nothing leaves the machine.

To try it on a real phone on the same Wi-Fi, start it with `SOOTABLE_HOST=0.0.0.0` (PowerShell:
`$env:SOOTABLE_HOST = "0.0.0.0"`), open the address it prints, and use *Add to Home screen*.

## What the app does

- **Home** shows today's smoke level on a ruler scale with the legal limit (2.45 m⁻¹) marked, four small tiles (today,
  7-day average, highest, change since baseline), an outlook ("projected to reach the limit around ...") and a trend chart.
- **Readings arrive by themselves.** The meter records once a day. The app collects them when it opens, every few minutes
  while it is open, and on pull-down. Nobody takes a reading by hand.
- **Alerts** only appear when the status changes (good, close to limit, over limit), and a single odd reading never raises
  one.
- **Several vehicles, one meter each.** Tap the vehicle name at the top to add another; each has its own readings,
  baseline, alerts and meter.
- **History and Settings.** Readings by day, CSV export, delete-all, and the connected meter's details.
- **Works like a phone app.** Installable on Android and iPhone, offline-capable, handles safe areas and the Android back
  gesture, and remembers where you were after a reload.
- **Developer tools** (hidden, not part of the product): open `/#dev`, or tap the version line in Settings five times.
  They run test scenarios such as a 1000-day wear-out or a dropped connection and show the raw Bluetooth bytes.

## About the hardware

The meter exists as a CAD design and has not been built. To show the whole data path anyway, `sootable/device_sim.py` is a
virtual device that behaves like the planned Arduino Nano + HM-10 firmware and talks to the app only through the real
byte frames of the protocol (sync byte, CRC-8, 20-byte Bluetooth chunks). The app's parser, CRC check and sync logic
cannot tell it from hardware, so connecting a real meter means replacing one transport class. **The readings in the demo
are generated, not measured.**

```
virtual device ──bytes──▶ simulated Bluetooth link ──20-byte chunks──▶ phone session (parse, CRC, sync)
                                                                              │
              phone UI (HTML/JS) ◀── JSON ── FastAPI ◀── analytics ◀── SQLite (local)
```

The meter shines an infrared LED through the exhaust, then flushes with clean air and measures again as a reference. The
app turns the two readings into the opacity coefficient **k = −(1 / L) · ln(i / i0)**, the quantity the legal limit is
written in.

## How it is built

Python 3, FastAPI and SQLite for the logic and storage; plain HTML, CSS and JavaScript for the UI (no framework, no build
step, charts drawn as inline SVG). The maths and alert rules are pure functions with no I/O, so they can move unchanged
into a native app.

| Path | What it is |
|---|---|
| `main.py` | Starts the app |
| `sootable/` | The backend: protocol (`crc8.py`, `frame.py`), maths and rules (`k.py`, `daily.py`, `alerts.py`), storage (`store.py`), sync (`session.py`), simulator (`device_sim.py`, `link.py`, `scenarios.py`), analytics (`engine.py`), API (`server.py`) |
| `web/` | The phone UI: `index.html`, `style.css`, `app.js`, service worker, fonts, logo and icons |
| `hardware/` | The 3D hardware demo (also published to GitHub Pages) |
| `tests/` | 94 automated tests |
| `docs/PROJECT.md` | Problem, solution, challenges, limitations, future work |
| `docs/LAUNCH.md` | How it runs on iOS and Android today and the route to the App Store and Google Play |

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```

They cover the byte-exact protocol examples, frame parsing under splits, merges and every single-bit corruption, the maths
and the legal-limit boundary, the alert rules, the simulator scenarios, storage limits, multiple vehicles and database
upgrades, pairing, and the HTTP API.

## Limits

This is a prototype. The meter is not built, so no real reading has been taken, and the infrared LED will need calibrating
against a reference opacimeter. Alert thresholds are placeholders until there is real data. The 2.45 m⁻¹ limit is for one
vehicle class. SootAble does not replace a PUC certificate, and works on diesel exhaust only. More in
[docs/PROJECT.md](docs/PROJECT.md).

## Credits and AI-usage disclosure

Generative AI was used, as the rules require us to disclose: we used Claude (Anthropic) through Claude Code to help plan
the project and write the code, tests and documentation. The product idea, the specification, the choice of SDG and the
design direction are the team's.

Open-source software: FastAPI, Uvicorn, Pydantic, SQLite, pytest, HTTPX, three.js. Fonts, bundled for offline use: Barlow,
Barlow Condensed and IBM Plex Mono (SIL Open Font License), Clash Display (Fontshare Free Font License). The legal limit
(2.45 m⁻¹, 65 Hartridge units) is the CMVR limit named in our specification.
