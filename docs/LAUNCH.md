# Launching SootAble as an app

## Where it stands today

SootAble is a **progressive web app** (PWA) with a Python backend. The phone UI is plain HTML, CSS and JavaScript; the
logic (protocol, maths, alerts, storage) is Python 3 with FastAPI and SQLite. It already behaves like an app on both iOS
and Android: full screen, safe areas for notches and gesture bars, the Android back button and gesture, a home-screen
icon (including an Android maskable icon and an iOS touch icon), an offline-capable shell, and it keeps its place across
reloads. It is **not** in the App Store or Google Play, and it cannot be there as it is, because those stores ship an app
that runs on the phone, and today the Python server runs on a computer.

## Option 1: use it as an installed web app (works now)

1. Run it on a computer: `SOOTABLE_HOST=0.0.0.0 python main.py` (PowerShell: `$env:SOOTABLE_HOST = "0.0.0.0"`).
2. Open the printed address on the phone (same Wi-Fi).
3. **Android (Chrome):** menu, *Install app*, or Settings, *Add to Home screen* inside SootAble.
   **iPhone (Safari):** Share, *Add to Home Screen*.

Limits to know about:

| | Android | iOS |
|---|---|---|
| Install as full-screen app | Yes | Yes (Safari only) |
| Offline app shell (service worker) | Yes, needs HTTPS or `localhost` | Yes, same condition |
| Vibration feedback | Yes | No (iOS does not allow it in web apps) |
| Notifications | While the app is open | Only for an installed home-screen app, and only while it is open |
| Bluetooth to the real meter | Chrome supports Web Bluetooth | **Not available in Safari** |

Over plain `http://` on a local network the phone treats the app as a bookmark with a nicer icon; the install prompt and
offline shell need HTTPS. A small cloud host or tunnel gives that, but then the data lives on that host, which is the
opposite of the "everything stays on your phone" design.

## Option 2: a store app (the real launch)

The Python backend is the part that has to change. Because everything the server does is local anyway (no accounts, no
cloud), the sensible route is to move that logic **onto the phone** and wrap the existing UI in a native shell.

**Recommended: Capacitor.**

1. **Wrap the front end.** Capacitor puts `web/` in a native Android and iOS project, unchanged.
2. **Port the logic to TypeScript.** `crc8.py`, `frame.py`, `k.py`, `daily.py`, `alerts.py` and `engine.py` are pure
   functions with no I/O, and the tests (`tests/`) describe the exact behaviour, so they translate directly and the test
   suite can be ported with them. Replace `api()` in `app.js` with calls to this local code.
3. **Storage:** SQLite on the phone through a Capacitor SQLite plugin. The schema and migrations in `store.py` carry over.
4. **Bluetooth:** replace the simulated transport with a BLE plugin (for example `@capacitor-community/bluetooth-le`).
   The frame protocol is already byte-exact, only the transport class changes. This is where the real hardware comes in:
   the HM-10 in the design is a Bluetooth Low Energy module, which both platforms can use, but it only forwards 20-byte
   serial chunks; an ESP32 (planned replacement for the Nano and HM-10) also gives proper pairing and firmware updates.
5. **Native extras:** local notifications for the daily reminder, a share sheet for the CSV export, the real app icon and
   splash screen.

Alternatives: **React Native** or **Flutter** (a full rewrite of the UI, better native feel, more work), or keep the
Python backend and ship only the web app (no store listing).

## Publishing

| | Google Play | Apple App Store |
|---|---|---|
| Developer account | One-time fee, about US$25 | About US$99 per year |
| Build needs | Android Studio (any OS) | A Mac with Xcode, or a cloud build service |
| Test before release | Internal and closed testing tracks (new personal accounts may need a set number of testers for a set number of days) | TestFlight |
| Required | Privacy policy, Data safety form, content rating, screenshots, icon | Privacy policy, App Privacy labels, screenshots, review notes |
| Review | Usually hours to a few days | Usually one to three days; a hardware companion app must explain the meter to the reviewer |

Fees and rules change, so check both stores' current pages before relying on these numbers.

Things specific to SootAble for the reviews:

- The privacy story is simple and should be stated plainly: no account, no analytics, no data leaves the phone.
- The app needs Bluetooth (and, on Android 12 and older, location permission for scanning). Explain why in the permission
  text.
- State that it does not replace a PUC certificate, as the app already does.
- Give the reviewer a way to see the app without the physical meter. The *Use demo data* choice exists for this.

## A realistic order of work

1. Capacitor shell and TypeScript port of the logic, tests passing (the bulk of the work).
2. Real BLE transport against a hardware prototype, then calibration against a reference opacimeter.
3. Closed test with a few vehicle owners and a workshop.
4. Store listings, then release to Android first (cheaper and faster), then iOS.
