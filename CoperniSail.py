import random
import string
import hashlib
import streamlit as st
import hashlib
import hmac
from firebase_admin import credentials, firestore
import firebase_admin
import requests
import numpy as np
import copernicusmarine
import os
import math

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

def MakeBoat(key: str, waypoints: dict) -> dict:
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

def SaveBoat(boat_data: dict) -> None:
    """
    Saves the boat defined in the dictionary boat_data into the Firestore database.
    Uses credentials stored under [Firestore] in Streamlit secrets.
    """
    # 1. Initialize Firestore client using secrets stored under [Firestore]
    def get_firestore_client():
        if not firebase_admin._apps:
            secret_source = st.secrets.get("Firestore", st.secrets)
            cred_dict = dict(secret_source)
            if "private_key" in cred_dict:
                cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        return firestore.client(database_id="copernisail-boat-data")
    db = get_firestore_client()
    
    # 2. Extract the boat_key to use as the document ID
    boat_key = boat_data.get("boat_key")
    if not boat_key:
        raise ValueError("boat_data must contain a valid 'boat_key'.")

    # 3. Save or update the document in the 'sim_state' collection
    db.collection("sim_state").document(boat_key).set(boat_data)

from datetime import datetime, timezone
import firebase_admin
from firebase_admin import credentials, firestore
import streamlit as st


@st.cache_resource
def get_firestore_client():
  """Initializes and returns the Firestore client using Streamlit secrets."""
  if not firebase_admin._apps:
    secret_source = st.secrets.get("Firestore", st.secrets)
    cred_dict = dict(secret_source)
    if "private_key" in cred_dict:
      cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)

  # Connect to your named database
  return firestore.client(database_id="copernisail-boat-data")


def GetMyBoat(key):
  """Query the data of the boat with `key` in the Firestore database.

  Updates its last_update_time to now and returns a dictionary with the
  boat_data.
  """
  db = get_firestore_client()

  # Reference to the specific boat document by its key
  # (Adjust "boats" if your collection has a different name)
  doc_ref = db.collection("sim_state").document(key)

  doc = doc_ref.get()

  if not doc.exists:
    st.warning(f"No boat found with key: {key}")
    return None

  # Get the existing boat data as a dictionary
  boat_data = doc.to_dict()

  # Update last_update_time to current UTC time
  now_iso = datetime.now(timezone.utc).isoformat()
  doc_ref.update({"last_update_time": now_iso})

  # Optionally update the timestamp in the returned dictionary as well
  boat_data["last_update_time"] = now_iso

  return boat_data
from datetime import datetime, timezone
from firebase_admin import firestore


def GetLastBoat():
  """Query the data of the boat with the oldest last_update_time in the

  Firestore database. Update its last_update_time to now in UTC ISO format.
  Uses the secrets under [firestore] to login. Returns a dictionary with the
  boat_data.
  """
  db = get_firestore_client()  # Uses your cached Firestore connection with [firestore] secrets

  # Query the boats collection to find the boat with the oldest last_update_time
  query = (
      db.collection("sim_state")
      .order_by("last_update_time", direction=firestore.Query.ASCENDING)
      .limit(1)
  )
  docs = list(query.stream())

  if not docs:
    return None

  # Get the oldest document and its data
  doc = docs[0]
  boat_data = doc.to_dict()

  # Generate current UTC time in ISO format string
  now_iso = datetime.now(timezone.utc).isoformat()

  # Update the last_update_time field in Firestore
  doc.reference.update({"last_update_time": now_iso})

  # Update the timestamp in the returned dictionary as well
  boat_data["last_update_time"] = now_iso

  return boat_data

def GetCurrent(latitude,longitude):
# Fetch Ocean Currents
  # Copernicus Credentials check
  credentials_path = os.path.expanduser(
      "~/.copernicusmarine/.copernicusmarine-credentials"
  )
  if not os.path.exists(credentials_path):
    try:
      copernicusmarine.login(
          username=st.secrets["CopernicusMarine"]["username"],
          password=st.secrets["CopernicusMarine"]["password"],
      )
      st.write("Copernicus login done")
    except Exception as e:
      st.error(f"Copernicus login failed: {e}")
  try:
    now = datetime.now(timezone.utc)
    current_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    ds_curr = copernicusmarine.open_dataset(
        dataset_id="cmems_mod_nws_phy-cur_anfc_1.5km-2D_PT15M-i",
        minimum_latitude=latitude,
        maximum_latitude=latitude,
        minimum_longitude=longitude,
        maximum_longitude=longitude,
        start_datetime=current_time_str,
        end_datetime=current_time_str,
        variables=["uo", "vo"],
    )
    point_data_curr = ds_curr.sel(
        latitude=latitude, longitude=longitude, method="nearest"
    )
    eastward_current = point_data_curr["uo"].values[0]
    northward_current = point_data_curr["vo"].values[0]
  except Exception as e:
    eastward_current, northward_current = 0,0
    st.warning(f"Could not load current: {e}")
  return {"northward_current":northward_current,"eastward_current":eastward_current}

def GetWind(latitude,longitude):
  # Fetch Live Predicted Wind via Open-Meteo API (No API key required)
  w_speed_ms = 0.0
  wind_dir = 180.0
  try:
    weather_url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}"
        "&current=wind_speed_10m,wind_direction_10m&wind_speed_unit=ms"
    )
    resp = requests.get(weather_url, timeout=5)
    resp.raise_for_status()
    current_weather = resp.json().get("current", {})
    w_speed_ms = current_weather.get("wind_speed_10m", 0.0)
    wind_dir = current_weather.get("wind_direction_10m", 180.0)
    
  except Exception:
    st.warning("Could not load wind")
  # Convert meteorological wind direction (direction FROM which wind blows)
  # into eastward (u) and northward (v) velocity components.
  alpha = math.radians( wind_dir)
  east_wind = w_speed_ms * math.sin(alpha)
  north_wind = w_speed_ms * math.cos(alpha)
  return {"north_wind": north_wind, "east_wind": east_wind}

#key=GenerateKey()
#waypoint=GetWaypoint()
#boat_data=MakeBoat(key,waypoint)
#SaveBoat(boat_data)
boat_info = GetLastBoat()

if boat_info:
  #st.write(f"Loaded data for boat: {key}")
  current=GetCurrent(boat_info["latitude"],boat_info["longitude"])
  st.json(current)
  wind=GetWind(boat_info["latitude"],boat_info["longitude"])
  st.json(wind)
