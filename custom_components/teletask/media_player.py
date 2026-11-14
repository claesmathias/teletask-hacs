"""Teletask media player platform — audio zones (FNC_AUDIO)."""
from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import (
    AUDIO_MUTE,
    AUDIO_OFF,
    AUDIO_ON,
    AUDIO_PRESET_NEXT,
    AUDIO_PRESET_PREV,
    AUDIO_SOURCES,
    AUDIO_VOLUME_DOWN,
    AUDIO_VOLUME_UP,
    FunctionCode,
)
from .const import DOMAIN
from .entity import TeletaskEntity
from .hub import TeletaskHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TeletaskHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        TeletaskAudioZone(hub, comp) for comp in hub.get_components_by_function(FunctionCode.AUDIO)
    )


class TeletaskAudioZone(TeletaskEntity, MediaPlayerEntity):
    """An audio zone: power, volume steps, mute toggle, 8 sources, presets."""

    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
    )

    def __init__(self, hub: TeletaskHub, component: dict) -> None:
        super().__init__(hub, component)
        names = component.get("config", {}).get("sources") or []
        if isinstance(names, str):
            names = [n.strip() for n in names.split(",")]
        # Source n (1-8) is named by the n-th entry, or "Source n".
        self._sources = {
            n: (names[n - 1] if n <= len(names) and names[n - 1] else f"Source {n}")
            for n in AUDIO_SOURCES
        }
        # Only list the named sources when names are given.
        listed = range(1, len(names) + 1) if names else AUDIO_SOURCES
        self._attr_source_list = [self._sources[n] for n in listed if n in self._sources]

    @property
    def state(self) -> MediaPlayerState | None:
        state = self._state_dict.get("state")
        if state is None:
            return None
        return MediaPlayerState.ON if state == "ON" else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float | None:
        volume = self._state_dict.get("volume")
        return None if volume is None else volume / 100

    @property
    def source(self) -> str | None:
        number = self._state_dict.get("source")
        if number is None:
            return self._state_dict.get("source_name") or None
        return self._sources.get(number)

    @property
    def media_title(self) -> str | None:
        return self._state_dict.get("track_line1") or self._state_dict.get("source_name") or None

    @property
    def media_artist(self) -> str | None:
        return self._state_dict.get("track_line2") or None

    async def async_turn_on(self) -> None:
        await self._hub.async_audio_command(self._number, AUDIO_ON)
        self._hub.optimistic_merge(FunctionCode.AUDIO, self._number, {"state": "ON"})

    async def async_turn_off(self) -> None:
        await self._hub.async_audio_command(self._number, AUDIO_OFF)
        self._hub.optimistic_merge(FunctionCode.AUDIO, self._number, {"state": "OFF"})

    async def async_volume_up(self) -> None:
        await self._hub.async_audio_command(self._number, AUDIO_VOLUME_UP)

    async def async_volume_down(self) -> None:
        await self._hub.async_audio_command(self._number, AUDIO_VOLUME_DOWN)

    async def async_mute_volume(self, mute: bool) -> None:
        # The central only has a mute toggle and doesn't report the mute state.
        await self._hub.async_audio_command(self._number, AUDIO_MUTE)

    async def async_select_source(self, source: str) -> None:
        number = next((n for n, name in self._sources.items() if name == source), None)
        if number is None:
            raise ValueError(f"Unknown source {source!r}")
        await self._hub.async_audio_select_source(self._number, number)

    async def async_media_next_track(self) -> None:
        await self._hub.async_audio_command(self._number, AUDIO_PRESET_NEXT)

    async def async_media_previous_track(self) -> None:
        await self._hub.async_audio_command(self._number, AUDIO_PRESET_PREV)
