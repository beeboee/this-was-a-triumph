"""Config flow for GLaDOS Voice Lines."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN, NAME


class GladosVoiceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):  # type: ignore[no-untyped-def]
        """Create a single config entry."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=NAME, data={})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):  # type: ignore[no-untyped-def]
        """No options yet."""
        return GladosVoiceOptionsFlow(config_entry)


class GladosVoiceOptionsFlow(config_entries.OptionsFlow):
    """Options flow placeholder."""

    def __init__(self, config_entry):  # type: ignore[no-untyped-def]
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):  # type: ignore[no-untyped-def]
        """Return current options."""
        return self.async_create_entry(title="", data={})
