# Tigo Cloud

Integration of the Tigo Cloud into Home Assistant, for one or more systems.

## Coming from the legacy Tigo integration

This integration replaces the legacy one (https://github.com/MartinStoffel/tigo), which supports a single system only. It takes over your systems, and their sensors keep their entity ids, history and statistics, so the energy dashboard and automations carry on:

1. Install Tigo Cloud via HACS (button below) and restart Home Assistant.
2. Confirm the discovered Tigo system under Settings → Devices & services. Without the latest version of the legacy integration there is no discovery; add the Tigo Cloud integration instead, it suggests the system and login of the legacy one.
3. Once all systems are taken over, remove the legacy Tigo integration from HACS.

The sensors are now grouped in a device per system, so their names start with the system name, unless you renamed them.

## About

Currently quite basic, just integrates the panel data, since that is the Tigo hardware I have. 

![image](https://github.com/MartinStoffel/tigo/assets/52819829/5e79c8e0-7f75-4466-b1e8-5c553c136822)

Added current, hourly, daily, monthly and yearly production, as well as all time production.

![image](https://github.com/user-attachments/assets/62f184ae-28db-457a-8cbb-fed60282852d)

Any feedback is welcome!

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=MartinStoffel&repository=tigo_cloud&category=Integration)

You can install via HACS by adding this repository or manually by creating custom_components/tigo_cloud in your config directory and add the files of the respective directory in this repo.
