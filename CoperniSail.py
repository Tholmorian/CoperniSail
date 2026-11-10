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
from datetime import datetime, timedelta, timezone
import json

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

@st.cache_resource
def GetFirestoreClient():
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

def SaveBoat(boat_data: dict) -> None:
    """
    Saves the boat defined in the dictionary boat_data into the Firestore database.
    Uses credentials stored under [Firestore] in Streamlit secrets.
    """
    # 1. Initialize Firestore client using secrets stored under [Firestore]
    db = GetFirestoreClient()
    
    # 2. Extract the boat_key to use as the document ID
    boat_key = boat_data.get("boat_key")
    if not boat_key:
        raise ValueError("boat_data must contain a valid 'boat_key'.")

    # 3. Save or update the document in the 'sim_state' collection
    db.collection("sim_state").document(boat_key).set(boat_data)




def GetMyBoat(key):
  """Query the data of the boat with `key` in the Firestore database.

  Updates its last_update_time to now and returns a dictionary with the
  boat_data.
  """
  db = GetFirestoreClient()

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
  db = GetFirestoreClient()  # Uses your cached Firestore connection with [firestore] secrets

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
  east_wind = w_speed_ms * math.sin(wind_dir*np.pi/180)
  north_wind = w_speed_ms * math.cos(wind_dir*np.pi/180)
  st.write(f"wind angle: {wind_dir}")
  st.write(f"wind speed: {w_speed_ms}")
  return {"north_wind": north_wind, "east_wind": east_wind}

def GetAisData(latitude,longitude):
  # Fetch AIS Vessels
  radius_nm = 5
  lat_offset = radius_nm / 60.0
  lon_offset = radius_nm / (60.0 * math.cos(math.radians(latitude)))
  min_lat = latitude - lat_offset
  max_lat = latitude + lat_offset
  min_lon = longitude - lon_offset
  max_lon = longitude + lon_offset
  ais_url = f"https://ais.openwaters.io/v1/vessels?bbox={min_lat},{min_lon},{max_lat},{max_lon}"
  geo_data = None
  try:
    resp = requests.get(ais_url)
    resp.raise_for_status()
    geo_data = resp.json()
  except Exception:
    st.warning("Could not load AIS data")
  if geo_data and "features" in geo_data:
    AisData={"latitude":[],"longitude":[],"speed":[],"heading":[],"update_time":[],"length":[],"name":[]}
    for vessel in geo_data["features"]:
      props = vessel.get("properties", {})
      coords = vessel.get("geometry", {}).get("coordinates", [None, None])
      AisData["latitude"].append(coords[1])
      AisData["longitude"].append(coords[0])
      AisData["speed"].append(props.get("sog", 0))
      AisData["heading"].append(props.get("cog", 0))
      AisData["update_time"].append(props.get("seen"))
      AisData["length"].append(props.get("length"))
      AisData["name"].append(props.get("name"))
  return AisData

from roaring_landmask import RoaringLandmask

@st.cache_resource
def GetLandmask():
  return RoaringLandmask.new()

def CheckAground(latitude, longitude):
  # roaring-landmask expects longitude first, then latitude.
  return GetLandmask().contains(float(longitude), float(latitude))

def DrawBoatTriangle(latitude, longitude, length, heading):
  """Calculates the 3 vertices of a triangle centered at the boat's position,
  scaled to the given length with a width of 1/4 of the length,
  and oriented according to the heading (in degrees).
  Returns a dictionary with keys 'latitude' and 'longitude',
  each containing a list of 3 values [bow, port, starboard].
  """
  if not length or length <= 0:
    length = 20.0  # Default fallback length in meters
  # Width is 1/4 of the boat length as requested
  beam = length / 4.0
  if heading is None:
    heading = 0.0
  theta = math.radians(heading)
  meters_per_deg_lat = 111111.0
  meters_per_deg_lon = 111111.0 * math.cos(math.radians(latitude))
  # Bow and stern center offsets in meters
  bow_m_lat = (length / 2.0) * math.cos(theta)
  bow_m_lon = (length / 2.0) * math.sin(theta)
  stern_m_lat = -(length / 2.0) * math.cos(theta)
  stern_m_lon = -(length / 2.0) * math.sin(theta)
  # Starboard/Port beam offsets in meters
  right_m_lat = -(beam / 2.0) * math.sin(theta)
  right_m_lon = (beam / 2.0) * math.cos(theta)
  # Vertex coordinates
  bow_lat = latitude + (bow_m_lat / meters_per_deg_lat)
  bow_lon = longitude + (bow_m_lon / meters_per_deg_lon)
  port_lat = (
      latitude
      + (stern_m_lat / meters_per_deg_lat)
      - (right_m_lat / meters_per_deg_lat)
  )
  port_lon = (
      longitude
      + (stern_m_lon / meters_per_deg_lon)
      - (right_m_lon / meters_per_deg_lon)
  )
  stbd_lat = (
      latitude
      + (stern_m_lat / meters_per_deg_lat)
      + (right_m_lat / meters_per_deg_lat)
  )
  stbd_lon = (
      longitude
      + (stern_m_lon / meters_per_deg_lon)
      + (right_m_lon / meters_per_deg_lon)
  )
  return {
      "latitude": [bow_lat, port_lat, stbd_lat],
      "longitude": [bow_lon, port_lon, stbd_lon],
  }

import math


def CheckColision(boat_data, AIS_data):
  """Verifies collision between the current boat and the closest boat in AIS_data."""
  def project_polygon(axis, polygon):
    """Projects polygon vertices onto a given axis."""
    dots = [p[0] * axis[0] + p[1] * axis[1] for p in polygon]
    return min(dots), max(dots)
    Calculates triangles for both boats using DrawBoatTriangle and checks
    for intersection. Returns the AIS data dictionary of the collided boat,
    or an empty list [] otherwise.

    if not AIS_data:
      return []
        
  def triangles_intersect(tri1, tri2):
    """Checks if two triangles intersect using the Separating Axis Theorem (SAT)."""
    polygons = [tri1, tri2]
    for poly in polygons:
      for i in range(len(poly)):
        p1 = poly[i]
        p2 = poly[(i + 1) % len(poly)]
        # Edge vector and its perpendicular normal axis
        edge = (p2[0] - p1[0], p2[1] - p1[1])
        axis = (-edge[1], edge[0])
        # Project both triangles onto the axis
        min1, max1 = project_polygon(axis, tri1)
        min2, max2 = project_polygon(axis, tri2)
        # If there is a gap on any axis, they do not intersect
        if max1 < min2 or max2 < min1:
          return False
    return True
    
  # Helper function to extract position, length, and heading from boat structures
  # (Supports both standard dictionaries and GeoJSON feature dictionaries)
  def extract_boat_info(b):
    if isinstance(b, dict) and "properties" in b and "geometry" in b:
      props = b.get("properties", {})
      coords = b.get("geometry", {}).get("coordinates", [0, 0])
      lat = coords[1] if len(coords) > 1 else props.get("latitude", 0)
      lon = coords[0] if len(coords) > 0 else props.get("longitude", 0)
      length = props.get("length", 20.0)
      heading = props.get("cog") or props.get("heading") or 0.0
      return lat, lon, length, heading
    else:
      lat = b.get("latitude") or b.get("lat", 0)
      lon = b.get("longitude") or b.get("lon", 0)
      length = b.get("length", 20.0)
      heading = b.get("heading") or b.get("cog") or 0.0
      return lat, lon, length, heading
  my_lat, my_lon, my_len, my_head = extract_boat_info(boat_data)
  closest_boat = None
  min_dist = float("inf")
  # 1. Find the closest boat in AIS_data
  for vessel in AIS_data:
    v_lat, v_lon, _, _ = extract_boat_info(vessel)
    # Approximate Euclidean distance in degrees for proximity check
    dist = (v_lat - my_lat) ** 2 + (v_lon - my_lon) ** 2
    if dist < min_dist:
      min_dist = dist
      closest_boat = vessel
  if not closest_boat:
    return []
  # 2. Calculate triangles for both boats using DrawBoatTriangle
  my_triangle = DrawBoatTriangle(my_lat, my_lon, my_len, my_head)
  ais_lat, ais_lon, ais_len, ais_head = extract_boat_info(closest_boat)
  ais_triangle = DrawBoatTriangle(ais_lat, ais_lon, ais_len, ais_head)
  # Convert dictionaries to list of (lat, lon) coordinate tuples
  my_pts = list(zip(my_triangle["latitude"], my_triangle["longitude"]))
  ais_pts = list(zip(ais_triangle["latitude"], ais_triangle["longitude"]))
  # 3. Check for collision/interference between the two triangles
  if triangles_intersect(my_pts, ais_pts):
    return closest_boat
  return []

#key=GenerateKey()
#waypoint=GetWaypoint()
#boat_data=MakeBoat(key,waypoint)
#SaveBoat(boat_data)
BoatData = GetLastBoat()
st.write(BoatData)
AisData= GetAisData(BoatData["latitude"],BoatData["longitude"])
st.write(AisData)
colision=CheckColision(boat_data, AIS_data)
st.write(colision)

