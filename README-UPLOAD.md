# Aviation News UK — last-known aircraft status updater

This package adds a scheduled collector for registrations already listed in the Fleet Centre's `REG_DATA` object. It does **not** create a public live-flight tracker.

## Files in this package

- `scripts/refresh_aircraft_status.py` — reads registrations from the existing root `index.html`, queries adsb.lol by registration, and saves last-known observations.
- `.github/workflows/refresh-aircraft-status.yml` — runs once daily and commits the refreshed JSON.
- `data/aircraft-status.json` — initial empty data file; the first successful workflow run populates it.
- `frontend-integration.html` — optional UI snippet to add last-known status to the existing aircraft profile modal.

## Upload

Extract the ZIP into the root of the existing repository, preserving folder paths. It should create/replace these paths:

- `.github/workflows/refresh-aircraft-status.yml`
- `scripts/refresh_aircraft_status.py`
- `data/aircraft-status.json`

Do not replace your existing `index.html` with any file from this ZIP.

## Add the API key

In GitHub, open the repository's Settings → Secrets and variables → Actions → New repository secret.

- Name: `ADSBLOL_API_KEY`
- Value: your adsb.lol API key

The key is optional for the script, but adding the key gives you the quota associated with your account. Do not put it in the HTML or commit it to the repository.

## Enable and test

1. Open the repository's Actions tab.
2. Select **Refresh aircraft last-known data**.
3. Choose **Run workflow**.
4. Watch the run. It may take several minutes because the script queries registrations individually and pauses between requests.
5. A successful run commits `data/aircraft-status.json`.

The scheduled run is once daily at 03:23 UTC to stay within the free adhoc key's published 1,000 requests/day quota. If your key is a feeder key, adsb.lol documents a higher quota; frequency can be increased later after checking your exact key tier. The service publishes its data under ODbL 1.0 and asks users to provide attribution.

## Add the profile display

Open `frontend-integration.html`, copy its complete contents, and paste it into the existing `index.html` immediately before the closing `</body>` tag. This adds last-known ADS-B observations to the aircraft profile popup. It does not alter the existing fleet tables or registration data.

## Status interpretation

- **Recent airborne activity** — ADS-B reported a numeric barometric altitude within the last 2 days.
- **Recently detected on ground** — ADS-B reported `alt_baro: "ground"` within the last 2 days.
- **Possible storage** — at least five ground detections and no airborne detection for at least 7 days. This is deliberately low confidence and is not proof of storage.
- **Previously detected...** — an older observation exists.
- **No ADS-B detection recorded** — the API did not return a sighting. This is not evidence that an aircraft is retired, stored or inactive.

A last-known coordinate is not necessarily the aircraft's current location. Coverage depends on receiver availability, transponder operation and the adsb.lol network. The JSON keeps old observations when a registration is not returned by a later API request.

## Important limitation

This first version queries each registration once per scheduled run. The existing Fleet Centre currently contains hundreds of registration entries. The daily schedule is chosen to stay within the published 1,000/day adhoc API quota; a feeder key has a higher published quota. Check the quota attached to your key before increasing the schedule frequency.

This is a static GitHub Pages workflow. The browser reads the generated JSON file; no API key is exposed to visitors.
