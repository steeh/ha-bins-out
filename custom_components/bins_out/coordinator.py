"""Coordinator: owns bin config, persisted state and reminder timers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CALENDAR_LOOKAHEAD_DAYS,
    CALENDAR_REFRESH_MINUTES,
    CONF_BIN_COLOUR,
    CONF_BIN_ID,
    CONF_BIN_NAME,
    CONF_BINS,
    CONF_CALENDAR_ENTITY,
    CONF_COLLECTION_TIME,
    CONF_EVENING_TIME,
    CONF_FIRST_COLLECTION,
    CONF_INTERVAL_WEEKS,
    CONF_MATCH,
    CONF_MORNING_TIME,
    CONF_SOURCE,
    DEFAULT_COLLECTION_TIME,
    DEFAULT_EVENING_TIME,
    DEFAULT_MORNING_TIME,
    DOMAIN,
    EVENT_REMINDER,
    REMINDER_EVENING,
    REMINDER_FORGOTTEN,
    REMINDER_MORNING,
    SOURCE_CALENDAR,
    STORAGE_VERSION,
    UPCOMING_COUNT,
)
from .schedule import (
    BinSchedule,
    BinState,
    compute_state,
    dates_from_events,
    evening_message,
    forgotten_message,
    morning_message,
    spoken_name,
)

_LOGGER = logging.getLogger(__name__)

type BinsOutConfigEntry = ConfigEntry[BinsOutCoordinator]


async def async_calendar_events(
    hass: HomeAssistant, entity_id: str, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    """Events on a HA calendar entity, via the public calendar.get_events action."""
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": entity_id, "start_date_time": start, "end_date_time": end},
        blocking=True,
        return_response=True,
    )
    return response[entity_id]["events"]


class BinsOutCoordinator(DataUpdateCoordinator[dict[str, BinState]]):
    """Recomputes every bin's state once a minute."""

    config_entry: BinsOutConfigEntry

    def __init__(self, hass: HomeAssistant, entry: BinsOutConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=1),
        )
        opts = entry.options
        self.bins: dict[str, dict[str, Any]] = {
            b[CONF_BIN_ID]: b for b in opts.get(CONF_BINS, [])
        }
        self.evening_time = time.fromisoformat(
            opts.get(CONF_EVENING_TIME, DEFAULT_EVENING_TIME)
        )
        self.morning_time = time.fromisoformat(
            opts.get(CONF_MORNING_TIME, DEFAULT_MORNING_TIME)
        )
        self.collection_time = time.fromisoformat(
            opts.get(CONF_COLLECTION_TIME, DEFAULT_COLLECTION_TIME)
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._put_out: dict[str, date] = {}
        self._moved: dict[str, dict[date, date]] = {}
        self._cancelled: dict[str, set[date]] = {}
        # Last dates read from each calendar-sourced bin's calendar. Persisted, so
        # an outage of the calendar (or the council website behind it) keeps them.
        self._calendar_dates: dict[str, tuple[date, ...]] = {}
        self._calendar_fetched: datetime | None = None
        self._calendar_warned: set[str] = set()

    # ---- persistence -------------------------------------------------------

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}

        def per_bin(key: str) -> dict[str, Any]:
            return {k: v for k, v in stored.get(key, {}).items() if k in self.bins}

        self._put_out = {k: date.fromisoformat(d) for k, d in per_bin("put_out").items()}
        self._moved = {
            k: {date.fromisoformat(a): date.fromisoformat(b) for a, b in m.items()}
            for k, m in per_bin("moved").items()
        }
        self._cancelled = {
            k: {date.fromisoformat(d) for d in ds} for k, ds in per_bin("cancelled").items()
        }
        self._calendar_dates = {
            k: tuple(date.fromisoformat(d) for d in ds)
            for k, ds in per_bin("calendar_dates").items()
        }

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(
            lambda: {
                "put_out": {k: v.isoformat() for k, v in self._put_out.items()},
                "moved": {
                    bin_id: {k.isoformat(): v.isoformat() for k, v in m.items()}
                    for bin_id, m in self._moved.items()
                },
                "cancelled": {
                    k: sorted(d.isoformat() for d in ds) for k, ds in self._cancelled.items()
                },
                "calendar_dates": {
                    k: [d.isoformat() for d in ds] for k, ds in self._calendar_dates.items()
                },
            },
            1,
        )

    # ---- state -------------------------------------------------------------

    def is_calendar(self, bin_id: str) -> bool:
        return self.bins[bin_id].get(CONF_SOURCE) == SOURCE_CALENDAR

    def schedule(self, bin_id: str) -> BinSchedule:
        cfg = self.bins[bin_id]
        common = {
            "moved": self._moved.get(bin_id, {}),
            "cancelled": frozenset(self._cancelled.get(bin_id, ())),
        }
        if self.is_calendar(bin_id):
            return BinSchedule(fixed_dates=self._calendar_dates.get(bin_id, ()), **common)
        return BinSchedule(
            first_collection=date.fromisoformat(cfg[CONF_FIRST_COLLECTION]),
            interval_weeks=int(cfg[CONF_INTERVAL_WEEKS]),
            **common,
        )

    def moved(self, bin_id: str) -> dict[date, date]:
        return dict(self._moved.get(bin_id, {}))

    def cancelled(self, bin_id: str) -> list[date]:
        return sorted(self._cancelled.get(bin_id, ()))

    async def _async_refresh_calendars(self) -> None:
        """Re-read dates for calendar-sourced bins, at most every 30 minutes."""
        now = dt_util.now()
        if self._calendar_fetched and now - self._calendar_fetched < timedelta(
            minutes=CALENDAR_REFRESH_MINUTES
        ):
            return
        by_calendar: dict[str, list[str]] = {}
        for bin_id, cfg in self.bins.items():
            if self.is_calendar(bin_id):
                by_calendar.setdefault(cfg[CONF_CALENDAR_ENTITY], []).append(bin_id)
        if not by_calendar:
            return

        all_ok = True
        start = dt_util.start_of_local_day(now) - timedelta(days=1)
        for entity_id, bin_ids in by_calendar.items():
            try:
                events = await async_calendar_events(
                    self.hass, entity_id, start, start + timedelta(days=CALENDAR_LOOKAHEAD_DAYS)
                )
            except (HomeAssistantError, KeyError) as err:
                # Usually the calendar's integration hasn't finished starting; retry next minute.
                all_ok = False
                if entity_id not in self._calendar_warned:
                    self._calendar_warned.add(entity_id)
                    _LOGGER.warning("Can't read %s yet, using saved dates: %s", entity_id, err)
                continue
            self._calendar_warned.discard(entity_id)
            for bin_id in bin_ids:
                self._calendar_dates[bin_id] = dates_from_events(
                    events, self.bins[bin_id].get(CONF_MATCH, "")
                )
        self._save()
        if all_ok:
            self._calendar_fetched = now

    def spoken_name(self, bin_id: str) -> str:
        cfg = self.bins[bin_id]
        return spoken_name(cfg[CONF_BIN_NAME], cfg.get(CONF_BIN_COLOUR, ""))

    @callback
    def _compute(self) -> dict[str, BinState]:
        now = dt_util.now()
        today = now.date()
        if stale := [k for k, d in self._put_out.items() if d < today]:
            for k in stale:
                del self._put_out[k]
            self._save()
        return {
            bin_id: compute_state(
                self.schedule(bin_id),
                now,
                self._put_out.get(bin_id),
                self.evening_time,
                self.collection_time,
                UPCOMING_COUNT,
            )
            for bin_id in self.bins
        }

    async def _async_update_data(self) -> dict[str, BinState]:
        await self._async_refresh_calendars()
        return self._compute()

    @callback
    def _push(self) -> None:
        self.async_set_updated_data(self._compute())

    # ---- announcements -----------------------------------------------------

    def bins_where(self, predicate) -> list[str]:
        data = self.data or {}
        return [self.spoken_name(b) for b, s in data.items() if predicate(s)]

    def tonight_message(self) -> str | None:
        return evening_message(
            self.bins_where(lambda s: s.days_until == 1 and not s.put_out)
        )

    def morning_message(self) -> str | None:
        return morning_message(
            self.bins_where(lambda s: s.days_until == 0 and not s.put_out)
        )

    def forgotten_message(self) -> str | None:
        return forgotten_message(self.bins_where(lambda s: s.forgotten))

    @callback
    def async_setup_reminders(self) -> None:
        """Fire `bins_out_reminder` events at the configured times."""

        def make(kind: str, get_message):
            @callback
            def _fire(_now) -> None:
                self._push()
                if message := get_message():
                    self.hass.bus.async_fire(
                        EVENT_REMINDER, {"type": kind, "message": message}
                    )

            return _fire

        for kind, at, get_message in (
            (REMINDER_EVENING, self.evening_time, self.tonight_message),
            (REMINDER_MORNING, self.morning_time, self.morning_message),
            (REMINDER_FORGOTTEN, self.collection_time, self.forgotten_message),
        ):
            self.config_entry.async_on_unload(
                async_track_time_change(
                    self.hass,
                    make(kind, get_message),
                    hour=at.hour,
                    minute=at.minute,
                    second=at.second,
                )
            )

    # ---- actions -----------------------------------------------------------

    def resolve_bin(self, ref: str) -> str:
        """Find a bin by id or (case-insensitive) name."""
        if ref in self.bins:
            return ref
        for bin_id, cfg in self.bins.items():
            if cfg[CONF_BIN_NAME].strip().lower() == ref.strip().lower():
                return bin_id
        raise ServiceValidationError(f"No bin called '{ref}'")

    @callback
    def set_put_out(self, bin_id: str, put_out: bool) -> None:
        if put_out:
            nxt = self.schedule(bin_id).next_collection(dt_util.now().date())
            if nxt is None:
                raise ServiceValidationError("This bin has no upcoming collection")
            self._put_out[bin_id] = nxt
        else:
            self._put_out.pop(bin_id, None)
        self._save()
        self._push()

    @callback
    def move_collection(self, bin_id: str, original: date, new: date) -> None:
        self._moved.setdefault(bin_id, {})[original] = new
        self._save()
        self._push()

    @callback
    def clear_moved(self, bin_id: str) -> None:
        self._moved.pop(bin_id, None)
        self._save()
        self._push()

    @callback
    def cancel_collection(self, bin_id: str, day: date) -> None:
        self._cancelled.setdefault(bin_id, set()).add(day)
        if self._put_out.get(bin_id) == day:
            del self._put_out[bin_id]
        self._save()
        self._push()

    @callback
    def restore_collection(self, bin_id: str, day: date) -> None:
        if day not in self._cancelled.get(bin_id, set()):
            raise ServiceValidationError(f"{day.isoformat()} isn't cancelled for this bin")
        self._cancelled[bin_id].discard(day)
        self._save()
        self._push()
