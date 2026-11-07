from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .coordinator import TauronAmiplusUpdateCoordinator
from .outage_coordinator import TauronOutageCoordinator


@dataclass
class TauronAmiplusRuntimeData:
    coordinator: TauronAmiplusUpdateCoordinator


type TauronAmiplusConfigEntry = ConfigEntry[TauronAmiplusRuntimeData]

type TauronOutageConfigEntry = ConfigEntry[TauronOutageCoordinator]
