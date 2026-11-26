# Sender-PC profiles and auto receive

Date: 2026-11-26. Branch: `feat/receiver-profiles-auto`, stacked on `feat/supabase-ui-redesign` (PR #21).

## Intent

Lucas sends files from several PCs (for example "PC BNP" and "PC PERSO") into the same receiver and capture card. Today he re-selects settings, often recalibrates, and must click **Start** on the receiver for every file. He wants:

1. **Profiles**: one named profile per sender PC that remembers its settings and its own calibration, editable later, so switching PCs gives back exactly what that PC needs.
2. **Auto receive**: the receiver stays armed and receives as soon as the sender transmits, file after file, without clicking Start.

## Facts that shape the design

- `POST /api/receive/start` creates one `ReceiverWorker`. It waits for calibration frames (`_wait_for_preflight`), receives **one** file, publishes `complete` and ends.
- Calibration is cached in `calibration.json` under `HDMI_TRANSFER_STATE_DIR`, keyed by `calibration_key(device_identity, open_device, backend, profile geometry, capture_shape)`. The sender PC is not part of the key, so two PCs on the same card and settings overwrite one slot.
- A cached sampling is only a first candidate (`hints[key]`). Three fresh CRC-valid calibration frames must confirm a geometry before any data is accepted. Trying more candidates is therefore safe.
- Receiver UI settings live in browser `localStorage` (`hdmi_transfer_settings`). History has just moved to SQLite on the server (`HistoryStore`).

## Goals

- Create, rename, edit and delete sender-PC profiles. A profile holds: name, capture device (by device name, with index as fallback), transfer profile (speed/balanced/quality), mode, bpc, and preview quality. Auto receive is a separate receiver-wide switch (see Decisions).
- Each profile has its own calibration entries.
- One **active profile**, chosen by Lucas on the receiver. Selecting it fills the Receive controls.
- Calibration lookup order when a transfer starts: active profile, then the other profiles that use the same capture device, then full calibration.
- When another profile's calibration matches, the receiver switches the active profile to it, says so in the log and status, and continues.
- Auto receive, when switched on with a profile active: the server arms a worker by itself and re-arms it after every completed file.

## Non-goals

- The receiver does not identify the sender PC from the signal (no protocol change, no sender-side profile name).
- No profiles on the sender page (`sender.html` stays offline and stateless).
- No sync of profiles between receivers.
- CLI (`hdmi-recv`) keeps working as today, without profiles.

## Anti-goals (failure even if it works)

- Auto receive spinning in a loop on errors, or hogging CPU with no way to stop it.
- A stored calibration accepted without fresh-frame validation.
- Losing today's behaviour for people who never create a profile.

## Approaches considered

| | A. Server side (picked) | B. In the Receive page |
|---|---|---|
| Profiles stored | SQLite on the receiver, next to history | Browser `localStorage` |
| Calibration per profile | Yes, profile id joins the calibration key | Not possible, calibration lives on the server |
| Auto receive runs | In the server, page open or not | Only while the Receive tab is open and awake |
| Cost | More Python: store, routes, supervisor, tests | Less code |

Lucas picked **A**. B also cannot do the "find a matching profile" fallback, because that needs per-profile calibration on the server.

## Design

### Storage: `ProfileStore` (`src/adapters/profile_store.py`)

- SQLite file `profiles.sqlite3` in `HDMI_TRANSFER_STATE_DIR` (same pattern as `HistoryStore`: best effort, a broken database logs and never blocks a transfer).
- Table `profiles(id INTEGER PK, name TEXT UNIQUE NOT NULL, device_name TEXT, device_index INTEGER, profile TEXT, mode TEXT, bpc INTEGER, preview_quality INTEGER, created_at, updated_at)`.
- Table `state(key TEXT PK, value TEXT)` holding `active_profile_id` and `auto_receive`.
- Values are validated against the same allowed sets as `/api/receive/start` (known profile names, mode in fountain/sequential/auto, bpc 1-3).

### Calibration per profile

- `calibration_key` gets an optional `sender_profile` argument. Absent (no profile) keeps the exact current key, so existing caches and the CLI are untouched.
- Worker receives `sender_profile_id` and `fallback_profile_ids` (other profiles on the same capture device, most recently used first).
- In `_wait_for_preflight`, the candidate samplings for a key become a short ordered list: active profile hint, then the fallback profiles' hints. Each is tried as the starting geometry exactly as `hints[key]` is today; validation (three unique CRC-valid frames) is unchanged.
- On success the sampling is saved under the key of the profile that matched. If that is a fallback profile, the worker publishes `status` with `matched_profile_id` and the server sets it as active profile.
- If no hint validates, today's full calibration runs and the result is saved for the active profile.
- A profile's transfer settings must equal the worker's settings for its hint to be tried (same geometry). Profiles with other settings are skipped in v1. Builder call: log which profiles were skipped.

### Auto receive supervisor (`src/application/auto_receive.py`)

- One background thread owned by the app, started in `create_app` (not in `runtime=False` test apps unless asked).
- Loop: if auto receive is on, a profile is active, no worker is alive and auto is not paused, start a worker with that profile's settings through the same code path as `/api/receive/start` (extract that body into a function both use).
- After `complete`: re-arm after a short delay (1 s) so the UI can show the result.
- After `error`: count consecutive errors; after 3, pause auto receive and publish the reason. A successful file resets the count.
- Manual **Stop** pauses auto receive until it is turned on again (toggle or profile change). **Start** and **Recalibrate** keep working by hand.
- Idle preview: while auto receive is on, the armed worker supplies the preview, so the separate idle preview capture is not opened.

### HTTP API (`src/interfaces/web/routes_profiles.py`)

- `GET /api/profiles` returns profiles plus `active_profile_id`.
- `POST /api/profiles`, `PUT /api/profiles/<id>`, `DELETE /api/profiles/<id>` (deleting the active profile clears it; its calibration entries are removed).
- `POST /api/profiles/<id>/activate`.
- `GET /api/receive/auto` returns `{enabled, paused, reason, consecutive_errors}`; `POST /api/receive/auto` with `{enabled}` toggles it for the active profile.
- `/api/receive/status` gains `active_profile_id`, `auto_receive` and `matched_profile_id`.

### UI

- **Receive sidebar**, above Capture: a "Sender PC" select (profiles plus "No profile"), an "Auto receive" switch, and an icon button to save the current controls into the profile. Selecting a profile fills Device, Profile, Mode, Encoding and Preview quality. Changing a control marks the profile as modified until saved.
- **Receive status**: when auto receive is armed, the status line says it is waiting for the sender. When a fallback profile matched: "Signal matched PC PERSO, switched profile".
- **Settings page**: a "Sender PCs" card listing profiles, with add, rename, edit and delete (delete asks for confirmation).
- Same Supabase-style components and tokens as the rest of the UI. Empty state: "No sender PC yet. Add one to keep its settings and calibration."

### Compatibility

- No profile selected: everything behaves exactly as today, including calibration keys.
- Existing `localStorage` settings stay the defaults when no profile is active.

## Testing

- `ProfileStore`: CRUD, unique names, validation, corrupt database does not raise.
- `calibration_key`: unchanged without profile; differs per profile.
- Preflight hint order: active hint first, fallback profile match switches profile, no match falls back to full calibration (fake capture frames as in existing worker tests).
- Supervisor: arms when enabled, re-arms after complete, pauses after 3 errors, pauses on manual stop (fake worker).
- Routes: CRUD, activate, auto toggle, status fields.
- Browser check on the running app: create two profiles, switch, toggle auto receive, confirm Start is not needed (with the real capture card when available).

## Decisions after the builder check (Claude's calls, for Lucas to confirm)

1. **Auto receive is one receiver-wide switch, not a per-profile flag.** The `auto_receive` column is dropped. This avoids a fallback match silently turning auto receive on or off. The switch is stored in the `state` table.
2. **Editing a Receive control while a profile is active saves it into that profile immediately** (no "modified, unsaved" state). Start always runs with the active profile's saved settings, and calibration lands in its slot. If auto receive is armed, a change stops the armed worker and the supervisor re-arms with the new settings.
3. **What re-arms and what pauses.** Only `complete` re-arms (after 1 s). These count as failures: `error`, a worker that ends without an event (for example all capture targets fell back), and a `stopped` that the user did not request. A worker that is replaced by a new Start, or stopped by the supervisor itself, does not count. After 3 consecutive failures auto receive pauses and shows why. A manual **Stop** pauses it at once. A pause is cleared by turning the switch off and on, choosing a profile, or a manual Start. A successful file resets the failure count.
4. **Auto receive survives a server restart.** It is meant to be "always ready". On boot, if the switch is on and a profile is active, the supervisor arms a worker after the device scan. The pause state lives only in memory, so a restart clears it. This means the capture card is held by the web server. Use the CLI (`hdmi-recv`) with auto receive off.
5. **Matching across profiles uses the transfer geometry only** (speed/balanced/quality and capture device), not bpc. Preflight already tries bpc 1 to 3. Hints are looked up for each bpc candidate under every matching profile. A match does not rewrite the matched profile's saved bpc.
6. **Calibration cleanup** (builder's call): each calibration entry records its `sender_profile` id next to the sampling, without bumping the cache version. Deleting a profile removes its entries. A new profile starts with no cached calibration and calibrates fully once.

## Left to the builder

- Exact log and status wording, icon choices, migration of `localStorage` defaults into a first profile (offer, never automatic).
- Ordering of fallback profiles beyond "most recently used first".
