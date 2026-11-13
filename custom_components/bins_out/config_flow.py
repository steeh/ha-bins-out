"""Config and options flows for Bins Out."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import (
    BIN_COLOURS,
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
    SOURCE_CALENDAR,
    SOURCE_MANUAL,
)
from .coordinator import async_calendar_events
from .schedule import dates_from_events

CONF_SELECTED_BIN = "selected_bin"
MATCH_LOOKAHEAD_DAYS = 90


def _settings_schema(current: dict[str, Any]) -> vol.Schema:
    time = selector.TimeSelector()
    return vol.Schema(
        {
            vol.Required(
                CONF_EVENING_TIME, default=current.get(CONF_EVENING_TIME, DEFAULT_EVENING_TIME)
            ): time,
            vol.Required(
                CONF_MORNING_TIME, default=current.get(CONF_MORNING_TIME, DEFAULT_MORNING_TIME)
            ): time,
            vol.Required(
                CONF_COLLECTION_TIME,
                default=current.get(CONF_COLLECTION_TIME, DEFAULT_COLLECTION_TIME),
            ): time,
        }
    )


def _name_taken(bins: list[dict[str, Any]], name: str, except_id: str | None = None) -> bool:
    return any(
        b[CONF_BIN_NAME].lower() == name.strip().lower() and b[CONF_BIN_ID] != except_id
        for b in bins
    )


class BinStepsMixin:
    """Steps for adding or editing one bin, shared by the config and options flows.

    bin (name, colour, where dates come from)
      -> bin_manual (a collection date + every N weeks)
      -> bin_calendar (which calendar) -> bin_match (which events on it)
    then `_async_bin_done(bin)`.
    """

    _draft: dict[str, Any]
    _edit_id: str | None = None

    def _existing_bins(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def _async_bin_done(self, bin_cfg: dict[str, Any]) -> ConfigFlowResult:
        raise NotImplementedError

    def _current(self) -> dict[str, Any]:
        return next(
            (b for b in self._existing_bins() if b[CONF_BIN_ID] == self._edit_id), {}
        )

    async def async_step_bin(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = self._current()
        if user_input is not None:
            if _name_taken(self._existing_bins(), user_input[CONF_BIN_NAME], self._edit_id):
                errors[CONF_BIN_NAME] = "name_taken"
            else:
                self._draft = {
                    CONF_BIN_ID: self._edit_id or uuid4().hex[:8],
                    CONF_BIN_NAME: user_input[CONF_BIN_NAME].strip(),
                    CONF_BIN_COLOUR: user_input[CONF_BIN_COLOUR],
                    CONF_SOURCE: user_input[CONF_SOURCE],
                }
                if user_input[CONF_SOURCE] == SOURCE_CALENDAR:
                    return await self.async_step_bin_calendar()
                return await self.async_step_bin_manual()
        defaults = user_input or current
        schema = vol.Schema(
            {
                vol.Required(CONF_BIN_NAME, default=defaults.get(CONF_BIN_NAME, vol.UNDEFINED)): (
                    selector.TextSelector()
                ),
                vol.Required(CONF_BIN_COLOUR, default=defaults.get(CONF_BIN_COLOUR, "black")): (
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(BIN_COLOURS),
                            translation_key="colour",
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                ),
                vol.Required(CONF_SOURCE, default=defaults.get(CONF_SOURCE, SOURCE_MANUAL)): (
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[SOURCE_MANUAL, SOURCE_CALENDAR],
                            translation_key="source",
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                ),
            }
        )
        return self.async_show_form(step_id="bin", data_schema=schema, errors=errors)

    async def async_step_bin_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None and CONF_FIRST_COLLECTION in user_input:
            return await self._async_bin_done(
                {
                    **self._draft,
                    CONF_FIRST_COLLECTION: user_input[CONF_FIRST_COLLECTION],
                    CONF_INTERVAL_WEEKS: int(user_input[CONF_INTERVAL_WEEKS]),
                }
            )
        current = self._current()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_FIRST_COLLECTION, default=current.get(CONF_FIRST_COLLECTION, vol.UNDEFINED)
                ): selector.DateSelector(),
                vol.Required(CONF_INTERVAL_WEEKS, default=current.get(CONF_INTERVAL_WEEKS, 1)): (
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=8, step=1, mode=selector.NumberSelectorMode.BOX
                        )
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="bin_manual",
            data_schema=schema,
            description_placeholders={"name": self._draft[CONF_BIN_NAME]},
        )

    async def async_step_bin_calendar(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None and CONF_CALENDAR_ENTITY in user_input:
            self._draft[CONF_CALENDAR_ENTITY] = user_input[CONF_CALENDAR_ENTITY]
            return await self.async_step_bin_match()
        current = self._current()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CALENDAR_ENTITY, default=current.get(CONF_CALENDAR_ENTITY, vol.UNDEFINED)
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="calendar")),
            }
        )
        return self.async_show_form(
            step_id="bin_calendar",
            data_schema=schema,
            description_placeholders={"name": self._draft[CONF_BIN_NAME]},
        )

    async def async_step_bin_match(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entity_id = self._draft[CONF_CALENDAR_ENTITY]
        start = dt_util.start_of_local_day()
        try:
            events = await async_calendar_events(
                self.hass, entity_id, start, start + timedelta(days=MATCH_LOOKAHEAD_DAYS)
            )
        except (HomeAssistantError, KeyError):
            events = []
        summaries = sorted({str(e.get("summary", "")) for e in events} - {""})

        errors: dict[str, str] = {}
        if user_input is not None:
            match = user_input[CONF_MATCH].strip()
            # An empty calendar is allowed (e.g. a garden bin paused for winter).
            if not match:
                errors[CONF_MATCH] = "no_match"
            elif events and not dates_from_events(events, match):
                errors[CONF_MATCH] = "no_match"
            else:
                return await self._async_bin_done({**self._draft, CONF_MATCH: match})

        name = self._draft[CONF_BIN_NAME].lower()
        colour = self._draft[CONF_BIN_COLOUR]
        suggested = self._current().get(CONF_MATCH) or next(
            (s for s in summaries if name in s.lower() or colour in s.lower()), vol.UNDEFINED
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_MATCH, default=suggested): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=summaries,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="bin_match",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "name": self._draft[CONF_BIN_NAME],
                "calendar": entity_id,
                "found": ", ".join(summaries) if summaries else "none in the next 90 days",
            },
        )


class BinsOutConfigFlow(BinStepsMixin, ConfigFlow, domain=DOMAIN):
    """Set reminder times, then add bins one by one."""

    VERSION = 1

    def __init__(self) -> None:
        self._options: dict[str, Any] = {CONF_BINS: []}

    def _existing_bins(self) -> list[dict[str, Any]]:
        return self._options[CONF_BINS]

    async def _async_bin_done(self, bin_cfg: dict[str, Any]) -> ConfigFlowResult:
        self._options[CONF_BINS].append(bin_cfg)
        return await self.async_step_more()

    async def async_step_more(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="more", menu_options=["bin", "finish"])

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_bin()
        return self.async_show_form(step_id="user", data_schema=_settings_schema({}))

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(title="Bins Out", data={}, options=self._options)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> BinsOutOptionsFlow:
        return BinsOutOptionsFlow()


class BinsOutOptionsFlow(BinStepsMixin, OptionsFlow):
    """Change times, add / edit / remove bins."""

    def _existing_bins(self) -> list[dict[str, Any]]:
        return list(self.config_entry.options.get(CONF_BINS, []))

    async def _async_bin_done(self, bin_cfg: dict[str, Any]) -> ConfigFlowResult:
        bins = self._existing_bins()
        if self._edit_id:
            bins = [bin_cfg if b[CONF_BIN_ID] == self._edit_id else b for b in bins]
        else:
            bins.append(bin_cfg)
        return self._save(**{CONF_BINS: bins})

    def _save(self, **changes: Any) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    def _bin_choices(self) -> selector.SelectSelector:
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(value=b[CONF_BIN_ID], label=b[CONF_BIN_NAME])
                    for b in self._existing_bins()
                ]
            )
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["settings", "bin"]
        if self._existing_bins():
            menu += ["edit_bin", "remove_bin"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self._save(**user_input)
        return self.async_show_form(
            step_id="settings", data_schema=_settings_schema(dict(self.config_entry.options))
        )

    async def async_step_edit_bin(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._edit_id = user_input[CONF_SELECTED_BIN]
            return await self.async_step_bin()
        return self.async_show_form(
            step_id="edit_bin",
            data_schema=vol.Schema({vol.Required(CONF_SELECTED_BIN): self._bin_choices()}),
        )

    async def async_step_remove_bin(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            remove = user_input[CONF_SELECTED_BIN]
            return self._save(
                **{CONF_BINS: [b for b in self._existing_bins() if b[CONF_BIN_ID] != remove]}
            )
        return self.async_show_form(
            step_id="remove_bin",
            data_schema=vol.Schema({vol.Required(CONF_SELECTED_BIN): self._bin_choices()}),
        )
