# SootAble: project documentation

## Problem statement

Diesel vehicle owners in India learn how much their engine smokes only at a Pollution Under Control (PUC) test, once or
twice a year. A worn injector or a clogged air filter can raise smoke for months in between, with nothing to show it. The
smoke is wasted fuel, a bigger share of black carbon and particulate pollution, and eventually a failed test and an
expensive repair that could have been small and early.

Nobody sees the slow change, because nobody measures often enough. This matters for **SDG 13 (Climate Action)**: black
carbon from poorly maintained diesel engines is a short-lived climate pollutant, and catching a degrading engine early
is one of the cheapest ways to cut it. It also helps air quality (SDG 11) and health (SDG 3).

## Solution

SootAble is a small, cheap opacity meter (target about Rs. 500) plus a phone app.

1. Once a day the meter, fitted to the exhaust, takes a reading by itself, with nothing for the owner to do. It draws in exhaust, shines an infrared LED
   through a chamber onto a photodiode, then flushes the chamber with clean air and measures again as a reference.
2. The meter sends the two readings to the phone. The app computes the opacity coefficient
   **k = −(1 / L) · ln(i / i0)** (i0 the clean-air reference, i the smoky reading, L the chamber length), the quantity the
   legal limit is written in (2.45 m⁻¹, or 65 Hartridge units, for the vehicle class we target).
3. The app stores the reading, smooths the trend, and warns the owner when the trend moves toward or past the limit,
   with one suggested next step. It also estimates when the limit will be reached at the current pace.

Because i0 is measured fresh for every test, slow drift in the LED and photodiode cancels out.

## Key features

- **Daily reading and a clear status** (Good / Close to limit / Over limit) from a 7-day average, so one odd day does not
  cause a scare. The status is always a word, never colour alone.
- **Instrument-style readout**: a large number over a ruler scale with the legal limit marked on it.
- **Trend** over 30 days, 1 year or the whole history (up to 1000 days, about 3 years, in about 130 KB), with a touch
  tooltip. Days with no valid reading are shown as gaps, never filled in.
- **Outlook**: a straight-line estimate of when the limit will be reached. Plain arithmetic, shown for information only.
- **Alerts that are not noise**: only when the status changes, at most one of each kind a week, with hysteresis so a value
  hovering at a threshold does not keep re-alerting. A single bad reading never raises an alarm.
- **Several vehicles, one meter each**: every vehicle has its own readings, baseline, alerts, outlook and meter. Adding a
  vehicle goes straight to connecting its meter, either over Bluetooth or with demo data for just that vehicle; a meter can
  be moved to another vehicle, and a vehicle without a meter cannot take readings.
- **Pairing**: the app searches for meters in range, lists them with signal strength, connects to the one you choose and
  runs the handshake; the firmware and sampling chamber shown are read from the meter's own frame. No meter, no readings.
- **Automatic daily readings**: the meter records on its own and the app collects them, so there is no manual step and no reminder to set.
- **Private and offline**: no account, no cloud, everything in a small local SQLite database. CSV export and delete-all.
- **Robust sync** of the meter's readings: a fresh reading is never lost to a dropped link or a corrupt frame.
- **Hardware demo**: a 3D simulator of the meter's CAD model (`/hardware`) showing the sensor, opacity and k live.
- **Mobile app behaviour**: phone-sized layout at any window size, installable on iOS and Android (safe areas, dynamic
  viewport, Android back button and gesture, maskable and touch icons, offline-capable shell), pull-down to sync,
  draggable sheets, haptics, labelled controls and keyboard-friendly sheets, and a reduced-motion mode.
- **Stays current and remembers**: it syncs the meters when opened and every few minutes, redraws when anything changes
  (including a new day), shows a banner instead of failing when it cannot reach its server, and restores the tab, scroll
  position, chart range and half-finished setup after a reload.

## Tech used

| Layer | Choice |
|---|---|
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Storage | SQLite (Python standard library), versioned migrations, auto-vacuum, one transaction per sync |
| Front end | Plain HTML, CSS and JavaScript with inline SVG for the charts and drawings; no framework, no build step |
| Protocol | A small binary frame format (sync byte, type, little-endian payload, CRC-8) that matches the Arduino + HM-10 BLE serial design |
| Simulator | A virtual device and link with fault injection (split frames, bit errors, dropped link, reboot) |
| Type | Barlow, Barlow Condensed, IBM Plex Mono (bundled, SIL OFL) |
| Tests | pytest and HTTPX |

The maths and alert rules (`crc8.py`, `frame.py`, `k.py`, `daily.py`, `alerts.py`) are pure functions with no I/O, so they
can move unchanged into a native phone app.

## Challenges faced

- **The hardware is only a CAD design.** We could not just wait for a device, so we built a virtual one that speaks the
  exact protocol. The app cannot tell it from the real thing, and the simulator doubles as a test rig with twelve scenarios.
- **Radio links are messy.** Bluetooth delivers at most 20 bytes at a time, so frames arrive split, merged or corrupted. The
  parser buffers and re-synchronises, and every single-bit corruption of a frame is caught by a test. Our first sync rule
  acknowledged the highest reading received, which would have deleted a reading lost to a corrupt frame; the app now
  acknowledges only up to the first gap and asks again.
- **Numbers on the legal boundary.** A reading of 2.4512 sits exactly on the 2.45 limit. We compare the value rounded to two
  decimals and test the boundary; the same care fixed a floating-point error at the 80% "close to limit" line.
- **Alerts that flapped.** On long, noisy histories a value hovering at a threshold re-alerted every week. We added
  hysteresis and a latch, and the 1000-day scenario now raises exactly three alerts.
- **Slow wear needs long history, a phone has little space.** Readings are kept for 1000 days and then removed (about
  130 KB), the baseline is saved separately because it comes from the oldest readings, and the database file shrinks
  after clean-up.
- **Several cars, several meters.** Every reading and alert belongs to a vehicle, and every meter is paired to exactly one
  vehicle (a vehicle has at most one meter). Syncing sends each meter's readings to its own vehicle; moving a meter syncs it
  first so readings it stored for the old vehicle are not misfiled. Older single-meter databases upgrade in place.
- **Pairing with no hardware.** Our first pairing screen was only an animation. It now does what pairing does: a scan
  returns the meter's advertisement, the user chooses, the app connects and reads the meter's handshake, and everything that
  needs a meter is blocked until one is paired. The scan finds the virtual device; the app code path is the real one.
- **A diagnostic tool is not a consumer app.** Our early screens exposed simulator controls and raw numbers, then swung to
  marketing copy and heavy animation. We settled on a quiet monitoring-app layout (a primary metric, small metric tiles, an
  insight card, a trend chart with the target range shaded), plain wording, short transitions, and all simulator controls
  behind a hidden switch.

## Limitations (honest)

- The meter is not built; every reading in the demo is generated by the simulator.
- Alert and status thresholds (80% of the limit, 1.5 times the baseline, the 7-day window) are placeholders that need real
  data.
- An infrared LED does not match the green-light detector of the legal test method, so real readings will need a
  calibration factor against a reference opacimeter.
- The 2.45 m⁻¹ limit is for one vehicle class; other Bharat Stage categories were not checked.
- SootAble does not replace a PUC certificate. It is for diesel exhaust only.

## Future improvements

- Build the meter and connect it over real Bluetooth (an ESP32 would replace the Nano and the HM-10), then calibrate
  against a reference opacimeter.
- A native Android and iOS app reusing the domain logic, with push reminders and background sync (route and store
  requirements in `LAUNCH.md`).
- Limits per vehicle category and emission norm, and thresholds tuned on real fleets.
- A shareable service report for the mechanic or PUC centre.
- Regional languages (Hindi, Telugu and others) and voice prompts for the reading flow.
- A fleet view for small transport operators.

## How it was tested

94 automated tests (`python -m pytest`): the protocol's byte-exact examples in both directions; parsing under every split
point, merged frames, garbage and every single-bit flip; the k formula, validity rules and legal-limit boundary; daily,
trend, baseline and alert rules; twelve simulator scenarios end to end (including 1000 days); storage limits and file
shrinking; multiple vehicles and the database upgrades; pairing (scan, connect, move, forget, one meter per vehicle, and no
readings without a meter); the HTTP API; and the installable-app files. The interface was also exercised in a real
browser at phone and laptop sizes, with and without reduced motion: no clipped text in the app bar, reload memory, the
back button, automatic updates, the offline banner and resuming setup.
