# Bins Out for Home Assistant

Tells you when your bins need to go out, nags you the night before and on the morning,
and notices when you forgot.

## Install

1. **Home Assistant 2026.11 or newer (Marketplace):** **Settings → Marketplace → Add from link** →
   enter `steeh/ha-bins-out` → **Add**, then open **Bins Out** and select **Install**.
   **Older Home Assistant (HACS):** HACS → ⋮ → **Custom repositories** → add
   `https://github.com/steeh/ha-bins-out` as type **Integration**, then search for **Bins Out** and **Download**.
   **Manually:** copy `custom_components/bins_out` into your HA `config/custom_components/` folder.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → Bins Out**.
4. Set your reminder times, then add each bin: a name, a colour, and where its collection dates come from (see below).

Add, edit or remove bins later with **Configure** on the integration.

## Collection dates

Each bin gets its dates one of two ways.

**Every few weeks from a date I know.** Enter any one date the bin is collected and how many weeks
apart collections are. Every other date is worked out from that.

**From a calendar (automatic).** The bin follows events on a Home Assistant calendar, so changes
from your council are picked up automatically. Bins Out re-reads the calendar every 30 minutes and
keeps the last dates it found if the calendar is temporarily unavailable. The best source is
[Waste Collection Schedule](https://github.com/mampfes/hacs_waste_collection_schedule) (Marketplace, or HACS on older versions),
which supports hundreds of councils.

Example: Knowsley Council (Liverpool)
1. In **Settings → Marketplace** (HACS on older versions), install **Waste Collection Schedule** and restart Home Assistant.
2. Settings → Devices & services → Add integration → **Waste Collection Schedule**. Choose the UK,
   then **Knowsley Metropolitan Borough Council**, and enter your **postcode** and **UPRN**.
   You can find your UPRN by entering your address at [findmyaddress.co.uk](https://www.findmyaddress.co.uk).
   (If your version only supports YAML, see its
   [Knowsley page](https://github.com/mampfes/hacs_waste_collection_schedule/blob/master/doc/source/knowsley_gov_uk.md).)
3. It creates a calendar of your collections.
4. Bins Out → **Configure** → **Edit a bin** (or **Add a bin**) → *Collection dates:*
   **From a calendar** → pick that calendar → pick the event name for this bin from the list.

**One-off changes** work with both kinds: move a collection with `bins_out.move_collection`, or
cancel one with `bins_out.cancel_collection` (see Services).

## Times

| Setting          | Default | What it does                                                              |
|------------------|---------|---------------------------------------------------------------------------|
| Evening reminder | 19:00   | Night before collection: reminder fires, "Needs to go out" turns on.      |
| Morning reminder | 06:30   | Collection day: reminder fires if a bin still isn't out.                  |
| Collection time  | 07:00   | After this, any bin not marked out counts as **forgotten**.               |

## Entities

Per bin (one device per bin):

| Entity                                | Example state                  |
|---------------------------------------|--------------------------------|
| `sensor.<bin>_next_collection`        | `2026-10-27` (+ `upcoming` list) |
| `sensor.<bin>_days_until_collection`  | `1`                            |
| `sensor.<bin>_status`                 | `upcoming` / `tomorrow` / `today` / `out` / `collected` / `forgotten` |
| `binary_sensor.<bin>_needs_to_go_out` | on from evening reminder until collection, unless put out |
| `binary_sensor.<bin>_forgotten`       | on if collection time passed and it wasn't put out |
| `switch.<bin>_put_out`                | turn on when it's at the kerb; clears itself after collection day |

Shared:

- `sensor.bins_out_next_collection`: days to the soonest collection, with every bin's details in attributes (used by the dashboard card).
- `calendar.bins_out_collections`: every collection, so it works in the HA calendar too.

## Services

- `bins_out.set_put_out`: `bin: Recycling`, `put_out: true`. Handy for an NFC tag stuck on the bin.
- `bins_out.move_collection`: one-off change such as a bank holiday:
  `bin: Recycling`, `original_date: 2026-12-25`, `new_date: 2026-12-27`.
- `bins_out.clear_moved`: remove all moved collections for a bin.
- `bins_out.cancel_collection`: a collection isn't happening (`bin: Recycling`, `date: 2026-12-25`).
  The bin moves on to its next collection and no reminders are sent for that day.
- `bins_out.restore_collection`: undo a cancellation (same fields).

You can run these from Developer tools → Actions, or from a dashboard button or script.

## Reminders and Alexa

At each reminder time, if there's something to say, the integration fires a `bins_out_reminder` event:

```yaml
event_type: bins_out_reminder
data:
  type: evening        # evening | morning | forgotten
  message: "Reminder: put the blue recycling bin out tonight. Collection is tomorrow."
```

**Alexa:** install [Alexa Media Player](https://github.com/alandtse/alexa_media_player) from the Marketplace (HACS on older versions),
then import the blueprint `blueprints/automation/bins_out/alexa_bin_reminders.yaml`
(copy it to `config/blueprints/automation/bins_out/`) and create an automation from it. Pick your Echo
devices, choose which reminders to speak and optionally add a phone notification.

**Tell Alexa it's out:** expose `switch.<bin>_put_out` to Alexa and say *"Alexa, turn on recycling put out"*,
or make an Alexa routine ("Alexa, I've put the bins out") that turns the switches on.

## Dashboard card

The card lives at `custom_components/bins_out/frontend/bins-out-card.js`. The integration adds it
as a Lovelace resource for you. If your resources are in YAML mode, add
`url: /bins_out_static/bins-out-card.js`, `type: module` yourself (change the URL, e.g. add
`?v=2`, after updating so browsers fetch the new card). Add it to a dashboard:

```yaml
type: custom:bins-out-card
entity: sensor.bins_out_next_collection
```

## Development

```bash
python -m venv venv && ./venv/bin/pip install pytest-homeassistant-custom-component home-assistant-frontend
./venv/bin/python -m pytest
```

## Ideas for later

- Auto-move collections around bank holidays (UK `holidays` package) instead of using `move_collection` by hand.
- A "bring the bin back in" reminder in the evening of collection day (the `collected` status already exists for this).
- Use a door or contact sensor on the side gate to mark bins out automatically.
- Holiday mode: pause reminders while you're away.
