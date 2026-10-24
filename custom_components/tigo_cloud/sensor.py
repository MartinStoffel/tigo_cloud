"""Sensors for Tigo."""

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, TIGO_URL
from .tigo import TigoConfigEntry, TigoCoordinator

PANEL_PROPERTIES = {
    "energy": {
        "name": "Energy",
        "native_unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "attr_icon": "mdi:solar-power-variant-outline",
    },
    "pin": {
        "name": "Power",
        "native_unit_of_measurement": UnitOfPower.WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "attr_icon": "mdi:solar-power",
    },
    "rssi": {
        "name": "RSSI",
        "native_unit_of_measurement": SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "attr_icon": "mdi:signal-variant",
    },
    "pwm": {
        "name": "PWM",
        "native_unit_of_measurement": None,
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "attr_icon": "mdi:square-wave",
    },
    "temp": {
        "name": "Temperature",
        "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "attr_icon": "mdi:thermometer",
    },
    "vin": {
        "name": "Voltage In",
        "native_unit_of_measurement": UnitOfElectricPotential.VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "attr_icon": "mdi:alpha-v-circle-outline",
    },
    "vout": {
        "name": "Voltage Out",
        "native_unit_of_measurement": UnitOfElectricPotential.VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "attr_icon": "mdi:alpha-v-circle",
    },
    "iin": {
        "name": "Current In",
        "native_unit_of_measurement": UnitOfElectricCurrent.AMPERE,
        "device_class": SensorDeviceClass.CURRENT,
        "state_class": SensorStateClass.MEASUREMENT,
        "attr_icon": "mdi:alpha-a-circle-outline",
    },
    "reclaimedPower": {
        "name": "Reclaimed Power",
        "native_unit_of_measurement": UnitOfPower.WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "attr_icon": "mdi:solar-power-variant",
    },
}

SUMMARY_PROPERTIES = {
    "now": {
        "name": "Current Production",
        "native_unit_of_measurement": UnitOfPower.WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "attr_icon": "mdi:solar-power-variant",
    },
    "hour": {
        "name": "Hourly Production",
        "native_unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "attr_icon": "mdi:solar-power-variant-outline",
    },
    "day": {
        "name": "Daily Production",
        "native_unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "attr_icon": "mdi:solar-power-variant-outline",
    },
    "month": {
        "name": "Monthly Production",
        "native_unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "attr_icon": "mdi:solar-power-variant-outline",
    },
    "year": {
        "name": "Yearly Production",
        "native_unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "attr_icon": "mdi:solar-power-variant-outline",
    },
    "allTime": {
        "name": "All Time Production",
        "native_unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "attr_icon": "mdi:solar-power-variant-outline",
    },
}


async def async_setup_entry(
    hass: HomeAssistant, entry: TigoConfigEntry, add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data

    entities: list[SensorEntity] = [
        TigoPanelSensor(panel, coordinator, key)
        for panel in coordinator.panels
        for key in PANEL_PROPERTIES
    ]
    entities += [TigoSummarySensor(coordinator, key) for key in SUMMARY_PROPERTIES]

    add_entities(entities)


class TigoSensor(CoordinatorEntity[TigoCoordinator], SensorEntity):
    """Common setup of the Tigo sensors, grouped under one device per system."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TigoCoordinator, properties: dict[str, Any]) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_native_unit_of_measurement = properties["native_unit_of_measurement"]
        self._attr_device_class = properties["device_class"]
        self._attr_state_class = properties["state_class"]
        self._attr_icon = properties["attr_icon"]
        self._attr_suggested_display_precision = properties.get(
            "suggested_display_precision"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.get_systemId())},
            name=coordinator.config_entry.title,
            manufacturer="Tigo Energy",
            configuration_url=TIGO_URL,
        )


class TigoSummarySensor(TigoSensor):
    """The Tigo summary sensor, showing daily, monthly and yearly stats."""

    def __init__(self, coordinator, property) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, SUMMARY_PROPERTIES[property])
        self._property = property
        self._attr_unique_id = DOMAIN + "tigo.summary." + coordinator.get_systemId() + "." + property
        self._attr_name = SUMMARY_PROPERTIES[property]["name"]

    @property
    def native_value(self) -> Any:
        """Return the summary reading."""
        return self.coordinator.data.get(self._property)


class TigoPanelSensor(TigoSensor):
    """The Tigo panel sensor."""

    def __init__(self, panel, coordinator, property) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, PANEL_PROPERTIES[property])
        self._property = property
        self._panel = panel
        self._attr_unique_id = DOMAIN + "tigo." + panel["T"] + "_" + property
        self._attr_name = panel["C"] + " " + PANEL_PROPERTIES[property]["name"]
        self._attr_extra_state_attributes = panel

    @property
    def native_value(self) -> Any:
        """Return the panel reading."""
        return self.coordinator.data.get(self._property, {}).get(str(self._panel["A"]))
