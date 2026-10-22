"""CoperniSail - main Streamlit script.

Entry point called by Streamlit when a user connects.
Every 60 s it updates all boats whose data is older than 5 min,
starting with the user's own boat.
"""
import copy
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from google.cloud import firestore

# The functions described in the specification live in this module
# (rename the module to match your project layout).
from copernisail_functions import (
    CheckAground,
    CheckColision,
    GetAisData,
    GetCurrent,
    GetLastBoat,
    GetMyBoat,
    GetUserInput,
    GetWind,
    MakeBoat,
    SimulateMovement,
    ValidKey,
)

# --------------------------------------------------------------------------
# Constants (adapt to your needs)
# --------------------------------------------------------------------------
LOOP_PERIOD_S = 60            # main loop period
BOAT_MAX_AGE = timedelta(minutes=5)     # boats older than this get updated
METEO_MAX_AGE = timedelta(minutes=10)   # wind/current refresh period
POSITION_MAX_AGE = timedelta(minutes=15)  # older than this: no simulation
SIM_STEP = timedelta(seconds=10)        # simulation step

BOATS_COLLECTION = "boats"

# Default/reset position and zones: (lat_min, lat_max, lon_min, lon_max)
DEFAULT_POSITION = {"latitude": 47.2, "longitude": -2.5}
START_ZONE = (47.10, 47.15, -2.60, -2.50)
ARRIVAL_ZONE = (47.30, 47.35, -2.60, -2.50)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value):
    """Return a timezone-aware UTC datetime (or None)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@st.cache_resource
def get_db() -> firestore.Client:
    return firestore.Client.from_service_account_info(dict(st.secrets["Firestore"]))


def update_boat(key: str, data: dict) -> None:
    """Write (merge) fields of a boat into the database."""
    get_db().collection(BOATS_COLLECTION).document(key).set(data, merge=True)


def in_zone(lat: float, lon: float, zone: tuple) -> bool:
    lat_min, lat_max, lon_min, lon_max = zone
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def reset_position(boat: dict) -> None:
    boat["latitude"] = DEFAULT_POSITION["latitude"]
    boat["longitude"] = DEFAULT_POSITION["longitude"]


def draw_map(placeholder, boat: dict, ais_data: dict) -> None:
    """Show my boat and the surrounding AIS boats on a map."""
    rows = [{"latitude": boat["latitude"], "longitude": boat["longitude"]}]
    for ais_boat in (ais_data or {}).values():
        rows.append(
            {"latitude": ais_boat["latitude"], "longitude": ais_boat["longitude"]}
        )
    placeholder.map(pd.DataFrame(rows))


# --------------------------------------------------------------------------
# Simulation of one boat
# --------------------------------------------------------------------------
def simulate_boat(boat: dict, ais_data: dict, now: datetime, previous_update: datetime) -> None:
    """Simulate displacement from previous_update to now in 10 s steps.

    The boat is modified in place only if the final position is kept.
    Collision or grounding resets the position.
    """
    # Position too old: no simulation, last_update_time only.
    if previous_update is None or now - previous_update > POSITION_MAX_AGE:
        return

    sim_boat = copy.deepcopy(boat)
    sim_ais = copy.deepcopy(ais_data)

    t = previous_update
    collided = False
    aground = False
    while t < now and not (collided or aground):
        t = min(t + SIM_STEP, now)
        SimulateMovement(t, sim_boat, sim_ais)

        collision = CheckColision(sim_boat, sim_ais)
        if len(collision) > 0:
            collided = True
            break
        if CheckAground(sim_boat["latitude"], sim_boat["longitude"]):
            aground = True
            break

    # Keep the new position
    boat["latitude"] = sim_boat["latitude"]
    boat["longitude"] = sim_boat["longitude"]

    # Collision or grounding: reset the position
    if collided or aground:
        reset_position(boat)


# --------------------------------------------------------------------------
# Update of one boat (one iteration of the inner loop)
# --------------------------------------------------------------------------
def process_boat(boat: dict, my_key: str, user_input: dict, map_placeholder) -> None:
    key = boat["key"]
    now = now_utc()
    previous_update = as_utc(boat.get("last_update_time"))

    # Claim the boat so another user does not update it at the same time
    update_boat(key, {"last_update_time": now})
    boat["last_update_time"] = now

    # Meteo (wind + current), refreshed if older than 10 min
    meteo_time = as_utc(boat.get("meteo_time"))
    if meteo_time is None or now - meteo_time > METEO_MAX_AGE:
        wind = GetWind(boat["latitude"], boat["longitude"])
        current = GetCurrent(boat["latitude"], boat["longitude"])
        boat.update(wind)      # northward / eastward wind
        boat.update(current)   # northward / eastward current
        boat["meteo_time"] = now

    # AIS data around the boat
    ais_data = GetAisData(boat["latitude"], boat["longitude"])

    # User interface values for my own boat
    is_my_boat = key == my_key
    if is_my_boat:
        boat["heading"] = user_input["heading"]
        boat["follow_wind"] = user_input["follow_wind"]
        boat["wind_angle"] = user_input["wind_angle"]

    # Movement simulation, collision and grounding checks
    simulate_boat(boat, ais_data, now, previous_update)

    # Start zone
    if in_zone(boat["latitude"], boat["longitude"], START_ZONE):
        boat["start_time"] = now

    # Arrival zone
    if in_zone(boat["latitude"], boat["longitude"], ARRIVAL_ZONE):
        start_time = as_utc(boat.get("start_time"))
        if start_time is not None:
            elapsed = (now - start_time).total_seconds()
            best = boat.get("best_time_to_arrival")
            if best is None or elapsed < best:
                boat["best_time_to_arrival"] = elapsed

    # Save everything at once
    update_boat(key, boat)

    # Map update for my boat
    if is_my_boat:
        draw_map(map_placeholder, boat, ais_data)


# --------------------------------------------------------------------------
# One full update cycle
# --------------------------------------------------------------------------
def run_cycle(map_placeholder) -> None:
    user_input = GetUserInput()
    my_key = user_input["boat_key"]
    done = set()

    # 1) My boat first
    my_boat = GetMyBoat(my_key)
    if not my_boat and ValidKey(my_key):
        MakeBoat(my_key)
        my_boat = GetMyBoat(my_key)
    if my_boat:
        process_boat(my_boat, my_key, user_input, map_placeholder)
        done.add(my_boat["key"])

    # 2) Then the oldest boats until all are more recent than 5 min
    while True:
        boat = GetLastBoat()
        if not boat:
            break
        last_update = as_utc(boat.get("last_update_time"))
        if last_update is not None and now_utc() - last_update < BOAT_MAX_AGE:
            break
        if boat["key"] in done:  # safety against an infinite loop
            break
        process_boat(boat, my_key, user_input, map_placeholder)
        done.add(boat["key"])


# --------------------------------------------------------------------------
# Streamlit entry point
# --------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="CoperniSail", layout="wide")
    st.title("CoperniSail")
    map_placeholder = st.empty()
    status = st.empty()

    while True:
        try:
            run_cycle(map_placeholder)
            status.caption(f"Last update: {now_utc():%Y-%m-%d %H:%M:%S} UTC")
        except Exception as exc:  # keep the loop alive
            status.error(f"Update error: {exc}")
        time.sleep(LOOP_PERIOD_S)


main()
