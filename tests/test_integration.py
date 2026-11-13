"""Integration tests running inside a real Home Assistant instance."""

from datetime import date, datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    MockPlatform,
    async_capture_events,
    async_fire_time_changed,
    mock_integration,
    mock_platform,
)

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.bins_out.const import DOMAIN, EVENT_REMINDER

OPTIONS = {
    "evening_time": "19:00:00",
    "morning_time": "06:30:00",
    "collection_time": "07:00:00",
    "bins": [
        {
            "id": "rec",
            "name": "Recycling",
            "colour": "blue",
            "first_collection": "2026-10-27",
            "interval_weeks": 2,
        },
        {
            "id": "gen",
            "name": "General",
            "colour": "black",
            "first_collection": "2026-11-03",
            "interval_weeks": 2,
        },
    ],
}


def local(*args) -> datetime:
    return datetime(*args, tzinfo=dt_util.get_default_time_zone())


@pytest.fixture
async def entry(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to(local(2026, 10, 26, 12, 0))
    entry = MockConfigEntry(domain=DOMAIN, title="Bins Out", data={}, options=OPTIONS)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


class CouncilCalendar(CalendarEntity):
    """Stands in for e.g. Waste Collection Schedule's calendar."""

    _attr_name = "Council bins"
    _attr_unique_id = "council_bins"

    def __init__(self, collections: dict[date, list[str]]) -> None:
        self.collections = collections

    @property
    def event(self) -> CalendarEvent | None:
        return None

    async def async_get_events(self, hass, start_date, end_date) -> list[CalendarEvent]:
        return [
            CalendarEvent(start=day, end=day + timedelta(days=1), summary=summary)
            for day, summaries in sorted(self.collections.items())
            if start_date.date() <= day < end_date.date()
            for summary in summaries
        ]


COUNCIL = {
    date(2026, 10, 27): ["Grey Bin"],
    date(2026, 10, 30): ["Maroon Bin", "Food Caddy"],
    date(2026, 11, 3): ["Grey Bin"],
    date(2026, 11, 13): ["Maroon Bin"],
}


async def setup_council_calendar(hass: HomeAssistant) -> CouncilCalendar:
    calendar = CouncilCalendar(dict(COUNCIL))

    async def setup_platform(hass, config, async_add_entities, discovery_info=None):
        async_add_entities([calendar])

    mock_integration(hass, MockModule("council"))
    mock_platform(hass, "council.calendar", MockPlatform(async_setup_platform=setup_platform))
    assert await async_setup_component(hass, "calendar", {"calendar": {"platform": "council"}})
    await hass.async_block_till_done()
    return calendar


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"evening_time": "20:00:00", "morning_time": "06:00:00", "collection_time": "07:00:00"},
    )
    assert result["step_id"] == "bin"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Garden", "colour": "green", "source": "manual"}
    )
    assert result["step_id"] == "bin_manual"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"first_collection": "2026-10-28", "interval_weeks": 2}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "bin"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "garden", "colour": "green", "source": "manual"}
    )
    assert result["errors"] == {"name": "name_taken"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Food", "colour": "grey", "source": "manual"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"first_collection": "2026-10-29", "interval_weeks": 1}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [b["name"] for b in result["options"]["bins"]] == ["Garden", "Food"]
    assert result["options"]["bins"][0]["source"] == "manual"
    assert result["options"]["evening_time"] == "20:00:00"


async def test_config_flow_calendar_bin(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to(local(2026, 10, 26, 12, 0))
    await setup_council_calendar(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"evening_time": "19:00:00", "morning_time": "06:30:00", "collection_time": "07:00:00"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "General", "colour": "grey", "source": "calendar"}
    )
    assert result["step_id"] == "bin_calendar"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"calendar_entity": "calendar.council_bins"}
    )
    assert result["step_id"] == "bin_match"
    # The dropdown offers the event names found on the calendar.
    options = result["data_schema"].schema["match"].config["options"]
    assert options == ["Food Caddy", "Grey Bin", "Maroon Bin"]
    assert "Grey Bin" in result["description_placeholders"]["found"]

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"match": "purple"})
    assert result["errors"] == {"match": "no_match"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"match": "grey"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["bins"][0] | {"id": "x"} == {
        "id": "x",
        "name": "General",
        "colour": "grey",
        "source": "calendar",
        "calendar_entity": "calendar.council_bins",
        "match": "grey",
    }
    await hass.async_block_till_done()
    assert hass.states.get("sensor.general_next_collection").state == "2026-10-27"


async def test_calendar_source_follows_council_changes(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to(local(2026, 10, 26, 12, 0))
    calendar = await setup_council_calendar(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            **{k: v for k, v in OPTIONS.items() if k != "bins"},
            "bins": [
                {"id": "gry", "name": "General", "colour": "grey", "source": "calendar",
                 "calendar_entity": "calendar.council_bins", "match": "Grey Bin"},
                {"id": "mar", "name": "Paper", "colour": "red", "source": "calendar",
                 "calendar_entity": "calendar.council_bins", "match": "maroon"},
            ],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.general_status").state == "tomorrow"
    assert hass.states.get("sensor.paper_next_collection").state == "2026-10-30"
    upcoming = hass.states.get("sensor.paper_next_collection").attributes["upcoming"]
    assert upcoming == ["2026-10-30", "2026-11-13"]

    # The council moves the grey bin; Bins Out picks it up on its next calendar read.
    del calendar.collections[date(2026, 10, 27)]
    calendar.collections[date(2026, 10, 28)] = ["Grey Bin"]
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.general_next_collection").state == "2026-10-28"

    # If the calendar disappears, the saved dates are kept.
    await calendar.async_remove()
    assert hass.states.get("calendar.council_bins").state == "unavailable"
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.general_next_collection").state == "2026-10-28"


async def test_cancel_and_restore(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.recycling_put_out"}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "cancel_collection", {"bin": "Recycling", "date": "2026-10-27"}, blocking=True
    )
    # Next collection skips to the one after; the put-out mark for the cancelled day is dropped.
    assert hass.states.get("sensor.recycling_next_collection").state == "2026-11-10"
    assert hass.states.get("switch.recycling_put_out").state == "off"
    summary = hass.states.get("sensor.bins_out_next_collection").attributes
    assert summary["tonight_message"] is None
    assert summary["bins"][0]["name"] == "General"
    assert next(b for b in summary["bins"] if b["id"] == "rec")["cancelled"] == ["2026-10-27"]

    await hass.services.async_call(
        DOMAIN, "restore_collection", {"bin": "Recycling", "date": "2026-10-27"}, blocking=True
    )
    assert hass.states.get("sensor.recycling_next_collection").state == "2026-10-27"

    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "restore_collection", {"bin": "Recycling", "date": "2026-10-27"}, blocking=True
        )


async def test_options_flow_add_and_remove(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "bin"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Garden", "colour": "green", "source": "manual"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"first_collection": "2026-10-28", "interval_weeks": 2}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get("sensor.garden_status") is not None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_bin"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"selected_bin": "gen"}
    )
    await hass.async_block_till_done()
    assert [b["id"] for b in entry.options["bins"]][:1] == ["rec"]
    assert hass.states.get("sensor.general_status") is None


async def test_entities(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert hass.states.get("sensor.recycling_next_collection").state == "2026-10-27"
    assert hass.states.get("sensor.recycling_days_until_collection").state == "1"
    assert hass.states.get("sensor.recycling_status").state == "tomorrow"
    assert hass.states.get("sensor.general_status").state == "upcoming"
    assert hass.states.get("binary_sensor.recycling_needs_to_go_out").state == "off"
    assert hass.states.get("switch.recycling_put_out").state == "off"

    summary = hass.states.get("sensor.bins_out_next_collection")
    assert summary.state == "1"
    bins = summary.attributes["bins"]
    assert [b["name"] for b in bins] == ["Recycling", "General"]
    assert bins[0]["colour_hex"] == "#1e6fd9"
    assert bins[0]["entities"]["put_out"] == "switch.recycling_put_out"
    assert summary.attributes["next_bins"] == ["Recycling"]
    assert "blue recycling bin" in summary.attributes["tonight_message"]

    cal = hass.states.get("calendar.bins_out_collections")
    assert cal.attributes["message"] == "Recycling"


async def test_put_out_switch_and_service(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.recycling_put_out"}, blocking=True
    )
    assert hass.states.get("switch.recycling_put_out").state == "on"
    assert hass.states.get("sensor.recycling_status").state == "out"
    assert hass.states.get("sensor.bins_out_next_collection").attributes["tonight_message"] is None

    await hass.services.async_call(
        DOMAIN, "set_put_out", {"bin": "recycling", "put_out": False}, blocking=True
    )
    assert hass.states.get("switch.recycling_put_out").state == "off"


async def test_reminder_events_and_forgotten(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    events = async_capture_events(hass, EVENT_REMINDER)

    freezer.move_to(local(2026, 10, 26, 19, 0, 0))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [e.data["type"] for e in events] == ["evening"]
    assert hass.states.get("binary_sensor.recycling_needs_to_go_out").state == "on"

    freezer.move_to(local(2026, 10, 27, 6, 30, 0))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert events[-1].data["type"] == "morning"

    freezer.move_to(local(2026, 10, 27, 7, 0, 0))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert events[-1].data["type"] == "forgotten"
    assert "blue recycling bin" in events[-1].data["message"]
    assert hass.states.get("binary_sensor.recycling_forgotten").state == "on"


async def test_move_collection_and_calendar(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.services.async_call(
        DOMAIN,
        "move_collection",
        {"bin": "Recycling", "original_date": "2026-10-27", "new_date": "2026-10-29"},
        blocking=True,
    )
    assert hass.states.get("sensor.recycling_next_collection").state == "2026-10-29"

    start = local(2026, 10, 26)
    resp = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": "calendar.bins_out_collections", "start_date_time": start,
         "end_date_time": start + timedelta(days=14)},
        blocking=True,
        return_response=True,
    )
    events = resp["calendar.bins_out_collections"]["events"]
    assert [(e["start"], e["summary"]) for e in events] == [
        ("2026-10-29", "Recycling"),
        ("2026-11-03", "General"),
    ]
    assert "Moved from" in events[0]["description"]


async def test_unknown_bin(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "set_put_out", {"bin": "nope"}, blocking=True)
