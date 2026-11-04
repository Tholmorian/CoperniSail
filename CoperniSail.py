import random
import string
import hashlib
import streamlit as st
import hashlib
import hmac
import streamlit as st

def GenerateKey():
    # 1. Generate 8 random characters (capital letters and numbers) [1]
    charset = string.ascii_uppercase + string.digits
    random_chars = ''.join(random.choices(charset, k=8))

    # 2. Retrieve the secret key under [KeyTester] secret_key [1]
    secret_key = st.secrets["KeyTester"]["secret_key"]

    # 3. Encode the 8 characters with the secret key into capital letters/numbers [1]
    hash_input = (random_chars + secret_key).encode('utf-8')
    digest = hashlib.sha256(hash_input).hexdigest().upper()
    encoded_chars = digest[:8]  # Extract 8 encoded characters

    # 4. Interlace the random and encoded characters [1]
    interlaced_key = ''.join(r + e for r, e in zip(random_chars, encoded_chars))

    return interlaced_key

def ValidKey(key: str) -> bool:
    """
    Validates a boat key according to the project specifications.
    Returns True if the key is valid, False otherwise.
    """
    # 1. Sanitize input and verify basic formatting (16 uppercase alphanumeric characters)
    if not isinstance(key, str):
        return False

    key = key.strip().upper()
    if len(key) != 16 or not key.isalnum():
        return False

    # 2. De-interlace the key into random characters (even indices) and encoded characters (odd indices)
    random_chars = "".join(key[i] for i in range(0, 16, 2))
    provided_encoded = "".join(key[i] for i in range(1, 16, 2))

    try:
        # 3. Retrieve the secret key from Streamlit secrets [KeyTester]
        secret_key = st.secrets["KeyTester"]["secret_key"]
    except Exception:
        return False

    # 4. Re-calculate the expected 8 encoded characters
    hash_input = (random_chars + secret_key).encode('utf-8')
    expected_encoded = hashlib.sha256(hash_input).hexdigest().upper()[:8]

    # 5. Constant-time comparison to verify validity
    return hmac.compare_digest(provided_encoded, expected_encoded)

from datetime import datetime, timedelta, timezone

def Makeboat(key: str, waypoints: dict) -> dict:
    """
    Returns a boat_data dictionary initialized with default values according to the project specification.
    """
    # Creation time in UTC ISO format
    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.isoformat()
    # Meteo update time defaults to creation time minus 1h
    meteo_iso = (now_utc - timedelta(hours=1)).isoformat()

    # Departure waypoint default location (waypoint number 1)
    start_lat = 50.97
    start_lon = 1.87

    # Extract latitude/longitude from waypoints if provided
    if isinstance(waypoints, dict):
        if 'latitude' in waypoints and 'longitude' in waypoints and len(waypoints['latitude']) > 0:
            start_lat = waypoints['latitude'][0]
            start_lon = waypoints['longitude'][0]

    # Build dictionary with default values specified in project documentation
    boat_data = {
        "boat_key": key,
        "boat_name": "x",
        "skipper_name": "x",
        "last_update_time": now_iso,
        "latitude": float(start_lat),
        "longitude": float(start_lon),
        "heading": 0,
        "heading_target": 0,
        "true_heading": 0,
        "tack": "stopped",
        "min_wind_angle": 50,
        "max_wind_angle": 180,
        "speed": 0,
        "best_time_to_arrival": 0,
        "start_time": now_iso,
        "meteo_update_time": meteo_iso,
        "wind_speed": 0,
        "wind_direction": 0,
        "current_speed": 0,
        "current_direction": 0,
        "information": "Welcome on board",
        "last_waypoint": 0
    }

    return boat_data

import json

def GetWaypoint() -> dict:
    """
    Reads 'waypoints.json' and returns a dictionary of lists:
    {
        'number': [1, 2, ...],
        'latitude': [50.97, 51.11, ...],
        'longitude': [1.87, 1.31, ...],
        'radius': [0.5, 0.5, ...]
    }
    """
    with open('waypoints.json', 'r', encoding='utf-8') as file:
        waypoints_list = json.load(file)

    # Initialize the dictionary with empty lists for each field
    waypoints_dict = {
        'number': [],
        'latitude': [],
        'longitude': [],
        'radius': []
    }

    # Iterate over the list of dictionaries and populate the lists
    for wp in waypoints_list:
        waypoints_dict['number'].append(wp['number'])
        waypoints_dict['latitude'].append(wp['latitude'])
        waypoints_dict['longitude'].append(wp['longitude'])
        waypoints_dict['radius'].append(wp['radius'])

    return waypoints_dict


waypoints=GetWaypoint()

boat_data=Makeboat(GenerateKey(), waypoints)
