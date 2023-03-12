"""Zaptec APM sensor platform."""
import logging
from datetime import timedelta, datetime, timezone
from typing import Any, Callable, Dict, Literal, Optional
from aiohttp import ClientSession
import pandas as pd

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.const import POWER_KILO_WATT
from homeassistant.helpers.typing import (
    ConfigType,
    DiscoveryInfoType,
    HomeAssistantType,
)

_LOGGER = logging.getLogger(__name__)
# Time between updating dataHub
SCAN_INTERVAL = timedelta(minutes=10)

CONF_ZAPTEC_USERNAME = "username"
CONF_ZAPTEC_PASSWORD = "password"
CONF_ZAPTEC_INSTALLATION_ID = "installation_id"


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ZAPTEC_USERNAME): cv.string,
        vol.Required(CONF_ZAPTEC_PASSWORD): cv.string,
        vol.Required(CONF_ZAPTEC_INSTALLATION_ID): cv.string,
    }
)



async def async_setup_platform(
    hass: HomeAssistantType,
    config: ConfigType,
    async_add_entities: Callable,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    """Set up the sensor platform."""
    session = async_get_clientsession(hass)

    power_sensor = ZaptecSensor(session, config, type="power", uid=f"{config[CONF_ZAPTEC_INSTALLATION_ID]}_power")
    charge_sensor = ZaptecSensor(session, config, type="charge", uid=f"{config[CONF_ZAPTEC_INSTALLATION_ID]}_charge")
    total_energy_sensor = ZaptecSensor(session, config, type="total_energy", uid=f"{config[CONF_ZAPTEC_INSTALLATION_ID]}_total_energy")
    async_add_entities([power_sensor, charge_sensor, total_energy_sensor], update_before_add=True)


class ZaptecSensor(Entity):
    """Representation of a Zaptec sensor."""

    def __init__(self, session: ClientSession, config: ConfigType, type: Literal["power", "charge", "total_energy"], uid: str):
        super().__init__()
        self.session = session
        self.config = config
        self._type = type
        self._uid = uid
        self._name = f"Zaptec {self._type}"
        self._state = None
        self._available = True
        self._attr_unit_of_measurement = POWER_KILO_WATT


    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._uid

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def state(self) -> Optional[str]:
        return self._state

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {}

    async def async_update(self):
        try:

            url = "https://api.zaptec.com/oauth/token"
            data = {'grant_type': 'password',
                    'username': self.config[CONF_ZAPTEC_USERNAME],
                    'password': self.config[CONF_ZAPTEC_PASSWORD]}
            response = await self.session.post(url, data=data)
            access_token = (await response.json())["access_token"]

            end = datetime.now(tz=timezone.utc)
            start = end - timedelta(hours=3)

            start_str = start.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]+"Z"
            end_str = end.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]+"Z"
            
            url = f"https://api.zaptec.com/api/installation/{self.config[CONF_ZAPTEC_INSTALLATION_ID]}/energySensorData?from={start_str}&to={end_str}"

            headers = {'Authorization': f'Bearer {access_token}'}
            response = await self.session.get(url, headers=headers)

            json = await response.json()
            charge_readings = json["ChargeEnergy"]
            power_readings = json["Readings"]

            power_df = pd.DataFrame(power_readings)
            power_df.index = pd.to_datetime(power_df['Timestamp'])
            power = power_df["Power"]

            charge_df = pd.DataFrame(charge_readings)
            charge_df.index = pd.to_datetime(charge_df['IntervalStart'])
            charge = charge_df["Value"]

            if self._type == "power":
                self._state = power.resample("10Min").mean().values[-1]
            elif self._type == "charge":
                 self._state = charge.resample("10Min").mean().values[-1]
            else:
                self._state = json["TotalEnergy"][-1]["Value"]
            
            self._available = True
        except Exception as e:
            self._available = False
            _LOGGER.exception(f"Error retrieving data from Zaptec. Error {e}")