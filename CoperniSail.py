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
from roaring_landmask import RoaringLandmask
import html
import folium
from streamlit_folium import st_folium

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
        "true_speed": 0,
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

  return boat_data



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
    current_speed=(eastward_current**2+northward_current**2)**0.5
    angle_rad = math.atan2(eastward_current, northward_current)
    current_direction = math.degrees(angle_rad) % 360
  except Exception as e:
    current_speed, current_direction = 0,0
    st.warning(f"Could not load current: {e}")
  return current_speed, current_direction

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
  return w_speed_ms,  wind_dir

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


@st.cache_resource
def GetLandmask():
  return RoaringLandmask.new()

def CheckAground(latitude, longitude):
  # roaring-landmask expects longitude first, then latitude.
  return GetLandmask().contains(float(longitude), float(latitude))

def DrawBoatTriangle(latitude, longitude, length, heading):
  #"""Calculates the 3 vertices of a triangle centered at the boat's position,
  #scaled to the given length with a width of 1/4 of the length,
  #and oriented according to the heading (in degrees).
  #Returns a dictionary with keys 'latitude' and 'longitude',
  #each containing a list of 3 values [bow, port, starboard].
  #"""
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


def CheckColision(boat_data, AIS_data):
  """Verifies collision between the current boat and the closest boat in AIS_data.

  AIS_data is a dictionary of lists (e.g., 'latitude', 'longitude', 'Length',
  'Heading', 'Name', etc.).
  """
  if not AIS_data or not isinstance(AIS_data, dict):
    return []

  # Helper function to find and retrieve list data across potential key naming variations
  def get_list(d, keys):
    for k in keys:
      if k in d and isinstance(d[k], list):
        return d[k]
    return []

  # Extract latitude and longitude lists from AIS_data dictionary
  lat_list = get_list(AIS_data, ["latitude", "lat", "Latitude"])
  lon_list = get_list(AIS_data, ["longitude", "lon", "Longitude"])

  if not lat_list or not lon_list or len(lat_list) == 0:
    return []

  # Extract current boat info
  def extract_boat_info(b):
    if isinstance(b, dict):
      lat = b.get("latitude") or b.get("lat", 0)
      lon = b.get("longitude") or b.get("lon", 0)
      length = b.get("length") or b.get("Length", 20.0)
      heading = b.get("heading") or b.get("Heading", 0.0)
      return lat, lon, length, heading
    return 0, 0, 20.0, 0.0

  my_lat, my_lon, my_len, my_head = extract_boat_info(boat_data)

  closest_index = -1
  min_dist = float("inf")
  num_boats = len(lat_list)

  # 1. Find the index of the closest boat in AIS_data lists
  for i in range(num_boats):
    v_lat = lat_list[i]
    v_lon = lon_list[i]
    # Approximate Euclidean distance in degrees
    dist = (v_lat - my_lat) ** 2 + (v_lon - my_lon) ** 2
    if dist < min_dist:
      min_dist = dist
      closest_index = i

  if closest_index == -1:
    return []

  # Construct a single dictionary representing the closest boat
  closest_boat = {}
  for k, v in AIS_data.items():
    if isinstance(v, list) and len(v) > closest_index:
      closest_boat[k] = v[closest_index]
    else:
      closest_boat[k] = v

  # Extract closest boat parameters for triangle calculation
  ais_lat = lat_list[closest_index]
  ais_lon = lon_list[closest_index]

  length_col = get_list(AIS_data, ["Length", "length"])
  ais_len = length_col[closest_index] if len(length_col) > closest_index else 20.0

  heading_col = get_list(AIS_data, ["Heading", "heading", "cog"])
  ais_head = (
      heading_col[closest_index] if len(heading_col) > closest_index else 0.0
  )

  # 2. Calculate triangles for both boats using DrawBoatTriangle
  my_triangle = DrawBoatTriangle(my_lat, my_lon, my_len, my_head)
  ais_triangle = DrawBoatTriangle(ais_lat, ais_lon, ais_len, ais_head)

  # Convert dictionaries to list of coordinate tuples
  my_pts = list(zip(my_triangle["latitude"], my_triangle["longitude"]))
  ais_pts = list(zip(ais_triangle["latitude"], ais_triangle["longitude"]))

  # 3. Check for collision using Separating Axis Theorem (SAT)
  def project_polygon(axis, polygon):
    dots = [p[0] * axis[0] + p[1] * axis[1] for p in polygon]
    return min(dots), max(dots)

  def triangles_intersect(tri1, tri2):
    polygons = [tri1, tri2]
    for poly in polygons:
      for j in range(len(poly)):
        p1 = poly[j]
        p2 = poly[(j + 1) % len(poly)]
        edge = (p2[0] - p1[0], p2[1] - p1[1])
        axis = (-edge[1], edge[0])
        min1, max1 = project_polygon(axis, tri1)
        min2, max2 = project_polygon(axis, tri2)
        if max1 < min2 or max2 < min1:
          return False
    return True

  if triangles_intersect(my_pts, ais_pts):
    return closest_boat
  return []





def SimulateMovement(time, boat_data, AIS_data):
    """
    Simulate the movement of the user's boat and surrounding AIS vessels.
    Parameters
    ----------
    time : datetime or ISO timestamp
        Time at which the simulation must finish.
    boat_data : dict
        User boat data from Firestore.
    AIS_data : dict of lists
        AIS vessel data, with parallel lists:
        latitude, longitude, speed, heading,
        update_time, length, name.
    Returns
    -------
    boat_data, AIS_data
        Both dictionaries are updated in place.
    """
  
    EARTH_RADIUS = 6371000.0
    MAX_BOAT_SPEED = 5.0 * 0.514444  # 5 knots in m/s

    def _to_utc(value):
        """Convert a datetime or ISO timestamp to timezone-aware UTC."""
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)


    def _normalize_angle(angle):
        """Normalize heading to [0, 360)."""
        return angle % 360.0


    def _signed_angle(angle):
        """Normalize an angle to [-180, 180)."""
        return (angle + 180.0) % 360.0 - 180.0


    def _move_position(latitude, longitude, east_velocity,
                      north_velocity, duration):
        """
        Move a GPS position using east/north velocity components.

        Velocity in m/s, duration in seconds.
        Returns (new_latitude, new_longitude).
        """
        east_distance = east_velocity * duration
        north_distance = north_velocity * duration

        distance = math.hypot(east_distance, north_distance)

        if distance == 0:
            return latitude, longitude

        bearing = math.atan2(east_distance, north_distance)
        angular_distance = distance / EARTH_RADIUS

        lat1 = math.radians(latitude)
        lon1 = math.radians(longitude)

        lat2 = math.asin(
            math.sin(lat1) * math.cos(angular_distance)
            + math.cos(lat1) * math.sin(angular_distance)
            * math.cos(bearing)
        )

        lon2 = lon1 + math.atan2(
            math.sin(bearing) * math.sin(angular_distance)
            * math.cos(lat1),
            math.cos(angular_distance)
            - math.sin(lat1) * math.sin(lat2)
        )

        new_latitude = math.degrees(lat2)
        new_longitude = (math.degrees(lon2) + 180) % 360 - 180

        return new_latitude, new_longitude


    def _heading_to_vector(speed, heading):
        """Convert speed and heading into east/north velocity."""
        angle = math.radians(heading)

        east = speed * math.sin(angle)
        north = speed * math.cos(angle)

        return east, north


    def _vector_to_heading(east, north):
        """Convert east/north velocity into heading."""
        if math.hypot(east, north) < 1e-9:
            return 0.0

        return _normalize_angle(math.degrees(math.atan2(east, north)))


    def _get_sailing_heading(boat_data):
        """
        Find the heading closest to heading_target,
        constrained by tack and true wind angle.
        """
        target = _normalize_angle(
            float(boat_data.get("heading_target", boat_data.get("heading", 0)))
        )

        tack = str(boat_data.get("tack", "stopped")).lower()

        if tack == "stopped":
            return _normalize_angle(float(boat_data.get("heading", 0)))
        
        wind_direction = float(boat_data.get("wind_direction", 0))

        min_angle = float(boat_data.get("min_wind_angle", 50))
        max_angle = float(boat_data.get("max_wind_angle", 180))

        # Avoid invalid wind-angle limits.
        min_angle = max(0.0, min(180.0, min_angle))
        max_angle = max(0.0, min(180.0, max_angle))

        if min_angle > max_angle:
            min_angle, max_angle = max_angle, min_angle

        # Signed angle between wind direction and target heading.
        relative_target = _signed_angle(target - wind_direction)

        if tack == "port":
            # Port tack: wind comes from the port side.
            relative_heading = min(max(relative_target, min_angle), max_angle)

        elif tack == "starboard":
            # Starboard tack: wind comes from the starboard side.
            relative_heading = min(max(relative_target, -max_angle), -min_angle)

        else:
            # Unknown tack: keep the boat stopped.
            return _normalize_angle(float(boat_data.get("heading", 0)))

        return _normalize_angle(wind_direction + relative_heading)


    def _get_ais_key(AIS_data, *names):
        """Find an AIS field, accepting lowercase and specification names."""
        for name in names:
            if name in AIS_data:
                return name
        return None

    simulation_time = _to_utc(time)
    target_time_str = simulation_time.isoformat()

    # ---------------------------------------------------------
    # 1. Simulate user's boat
    # ---------------------------------------------------------

    last_update = _to_utc(boat_data["last_update_time"])

    duration = (simulation_time - last_update).total_seconds()

    if duration > 0:

        latitude = float(boat_data["latitude"])
        longitude = float(boat_data["longitude"])

        # Sailing heading, constrained by wind angle and tack.
        heading = _get_sailing_heading(boat_data)

        boat_data["heading"] = heading

        tack = str(boat_data.get("tack", "stopped")).lower()

        # Sailing speed relative to the water.

        wind_speed = max(0.0, float(boat_data.get("wind_speed", 0)))

        sailing_speed = min(
            wind_speed / 2.0,
            MAX_BOAT_SPEED
        )
        boat_data["speed"] = sailing_speed 

        # Sailing velocity vector.
        boat_east, boat_north = _heading_to_vector(
            sailing_speed, heading
        )

        # Current velocity vector.
        current_speed = max(
            0.0, float(boat_data.get("current_speed", 0))
        )

        current_direction = float(
            boat_data.get("current_direction", 0)
        )

        current_east, current_north = _heading_to_vector(
            current_speed, current_direction
        )

        # Ground velocity = sailing velocity + current velocity.
        ground_east = boat_east + current_east
        ground_north = boat_north + current_north

        if tack == "stopped":
            sailing_speed = 0.0
            ground_east=0.0
            ground_north=0.0

        ground_speed = math.hypot(ground_east, ground_north)

        true_heading = _vector_to_heading(
            ground_east, ground_north
        )

        # Move the boat.
        new_latitude, new_longitude = _move_position(
            latitude,
            longitude,
            ground_east,
            ground_north,
            duration
        )

        # Update boat data.
        boat_data["latitude"] = new_latitude
        boat_data["longitude"] = new_longitude
        boat_data["true_heading"] = true_heading
        boat_data["true_speed"] = ground_speed

    # Always update the simulation timestamp.
    boat_data["last_update_time"] = target_time_str

    # ---------------------------------------------------------
    # 2. Simulate AIS vessels
    # ---------------------------------------------------------

    if not AIS_data:
        return boat_data, AIS_data

    required_keys = [
        "latitude", "longitude", "speed", "heading", "update_time"
    ]

    if any(key is None for key in required_keys):
        raise ValueError("AIS_data is missing a required field.")

    vessel_count = min(
        len(AIS_data["latitude"]),
        len(AIS_data["longitude"]),
        len(AIS_data["speed"]),
        len(AIS_data["heading"]),
        len(AIS_data["update_time"])
    )

    for i in range(vessel_count):

        if AIS_data["update_time"][i] is None:
            continue

        ais_update_time = _to_utc(AIS_data["update_time"][i])

        ais_duration = (
            simulation_time - ais_update_time
        ).total_seconds()

        # Do not move vessels with future timestamps.
        if ais_duration <= 0:
            continue

        ais_latitude = float(AIS_data["latitude"][i])
        ais_longitude = float(AIS_data["longitude"][i])

        ais_speed = max(0.0, float(AIS_data["speed"][i]))
        ais_heading = float(AIS_data["heading"][i])

        # AIS speed and heading are assumed to be
        # speed over ground and course over ground.
        ais_east, ais_north = _heading_to_vector(
            ais_speed, ais_heading
        )

        # Move vessel to simulation time.
        new_latitude, new_longitude = _move_position(
            ais_latitude,
            ais_longitude,
            ais_east,
            ais_north,
            ais_duration
        )

        AIS_data["latitude"][i] = new_latitude
        AIS_data["longitude"][i] = new_longitude
        AIS_data["update_time"][i] = target_time_str

    return boat_data, AIS_data


import math

def CheckWaypoint(latitude, longitude, waypoints):
    """
    Check if the boat is inside a waypoint passage zone.

    Parameters
    ----------
    latitude : float
        Boat latitude in decimal degrees.
    longitude : float
        Boat longitude in decimal degrees.

    waypoints : dict
        Dictionary containing:
        - number: list of waypoint numbers
        - latitude: list of waypoint latitudes
        - longitude: list of waypoint longitudes
        - radius: list of waypoint radii in nautical miles

    Returns
    -------
    int
        Waypoint number if inside a passage zone.
        0 if no waypoint is reached.
    """

    EARTH_RADIUS_NM = 3440.065

    for i in range(len(waypoints["number"])):

        wp_lat = waypoints["latitude"][i]
        wp_lon = waypoints["longitude"][i]
        radius = waypoints["radius"][i]

        # Convert coordinates to radians
        lat1 = math.radians(latitude)
        lon1 = math.radians(longitude)
        lat2 = math.radians(wp_lat)
        lon2 = math.radians(wp_lon)

        # Haversine distance
        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = (
            math.sin(dlat / 2)**2
            + math.cos(lat1) * math.cos(lat2)
            * math.sin(dlon / 2)**2
        )

        c = 2 * math.atan2(
            math.sqrt(a),
            math.sqrt(1 - a)
        )

        distance = EARTH_RADIUS_NM * c

        # Check if boat is inside waypoint radius
        if distance <= radius:
            return waypoints["number"][i]

    return 0


def DrawInterface(boat_data, AIS_data):
    """
    Draw the CoperniSail user interface.

    Parameters
    ----------
    boat_data : dict
        Current boat data.

    AIS_data : dict
        AIS vessel data containing lists:
        latitude, longitude, speed, heading,
        length, name and update_time.
    """

    # ---------------------------------------------------------
    # 1. Boat data
    # ---------------------------------------------------------

    latitude = float(boat_data["latitude"])
    longitude = float(boat_data["longitude"])

    heading = float(boat_data.get("true_heading", 0))
    speed = float(boat_data.get("true_speed", 0))

    speed_knots = speed * 1.943844

    boat_name = boat_data.get("boat_name", "My boat")
    boat_length = float(boat_data.get("length", 4.5))

    # ---------------------------------------------------------
    # 2. Interface layout
    # ---------------------------------------------------------

    # Boat key gets the full page width
    st.text_input(
        "Boat key",
        value=boat_data.get("boat_key", ""),
        type="password",
        key="boat_key",
        help="Enter your boat identification key"
    )

    # Wider control panel
    map_col, control_col = st.columns([3, 2], gap="medium")

    # =========================================================
    # 3. MAP
    # =========================================================

    with map_col:

        m = folium.Map(
            location=[latitude, longitude],
            zoom_start=11,
            control_scale=True,
            tiles=None
        )

        # Satellite background
        folium.TileLayer(
            tiles=(
                "https://server.arcgisonline.com/ArcGIS/"
                "rest/services/World_Imagery/MapServer/tile/"
                "{z}/{y}/{x}"
            ),
            attr="Tiles © Esri",
            name="Satellite"
        ).add_to(m)

        # -----------------------------------------------------
        # 5 NM circle
        # -----------------------------------------------------

        radius = 5 * 1852

        folium.Circle(
            location=[latitude, longitude],
            radius=radius,
            color="blue",
            weight=1,
            fill=False,
            tooltip="5 NM"
        ).add_to(m)

        # -----------------------------------------------------
        # Radial lines every 10 degrees
        # -----------------------------------------------------

        def DestinationPoint(lat, lon, bearing, distance):
            R = 6371000

            lat1 = math.radians(lat)
            lon1 = math.radians(lon)
            brng = math.radians(bearing)

            d = distance / R

            lat2 = math.asin(
                math.sin(lat1) * math.cos(d)
                + math.cos(lat1) * math.sin(d)
                * math.cos(brng)
            )

            lon2 = lon1 + math.atan2(
                math.sin(brng) * math.sin(d)
                * math.cos(lat1),
                math.cos(d)
                - math.sin(lat1) * math.sin(lat2)
            )

            return [
                math.degrees(lat2),
                math.degrees(lon2)
            ]

        for angle in range(0, 360, 10):

            end_point = DestinationPoint(
                latitude,
                longitude,
                angle,
                radius
            )

            folium.PolyLine(
                locations=[
                    [latitude, longitude],
                    end_point
                ],
                color="blue",
                weight=1,
                opacity=0.4
            ).add_to(m)

        # =====================================================
        # 4. USER BOAT
        # =====================================================

        triangle = DrawBoatTriangle(
            latitude,
            longitude,
            boat_length,
            heading
        )

        coordinates = list(zip(
            triangle["latitude"],
            triangle["longitude"]
        ))

        folium.Polygon(
            locations=coordinates,
            color="red",
            weight=2,
            fill=True,
            fill_color="red",
            fill_opacity=1,
            tooltip=boat_name
        ).add_to(m)


        # =====================================================
        # 5. AIS VESSELS
        # =====================================================

        def GetAISValue(key, index, default=None):

            values = AIS_data.get(
                key,
                AIS_data.get(key.lower(), [])
            )

            if isinstance(values, list) and index < len(values):
                value = values[index]

                if value is not None:
                    return value

            return default

        if isinstance(AIS_data, dict):

            ais_latitudes = AIS_data.get(
                "latitude",
                AIS_data.get("Latitude", [])
            )

            for i in range(len(ais_latitudes)):

                ais_lat = GetAISValue("latitude", i)
                ais_lon = GetAISValue("longitude", i)

                # Position is mandatory
                if ais_lat is None or ais_lon is None:
                    continue

                # Optional AIS information
                ais_name = GetAISValue("name", i, "Unknown")
                ais_length = float(GetAISValue("length", i, 10))
                ais_speed = float(GetAISValue("speed", i, 0))
                ais_heading = float(GetAISValue("heading", i, 0))

                triangle = DrawBoatTriangle(
                    float(ais_lat),
                    float(ais_lon),
                    ais_length,
                    ais_heading
                )

                coordinates = list(zip(
                    triangle["latitude"],
                    triangle["longitude"]
                ))

                tooltip = (
                    f"Name: {html.escape(str(ais_name))}<br>"
                    f"Length: {ais_length:.1f} m<br>"
                    f"Speed: {ais_speed * 1.943844:.1f} knots"
                )

                folium.Polygon(
                    locations=coordinates,
                    color="orange",
                    weight=1,
                    fill=True,
                    fill_color="orange",
                    fill_opacity=0.8,
                    tooltip=folium.Tooltip(tooltip)
                ).add_to(m)

        # =====================================================
        # 6. DISPLAY MAP
        # =====================================================

        st_folium(
            m,
            width=None,
            height=700,
            key="copernisail_map",
            returned_objects=[]
        )

    # =========================================================
    # 7. USER CONTROLS
    # =========================================================

    with control_col:

        st.subheader("Boat controls")

        st.subheader("Navigation")

        nav_col1, nav_col2 = st.columns(2)

        with nav_col1:
            st.metric(
                "True heading",
                f"{heading:.1f}°"
            )

        with nav_col2:
            st.metric(
                "True speed",
                f"{speed_knots:.2f} kn"
            )

        st.text_input(
            "Boat name",
            value=boat_data.get("boat_name", "x"),
            key="boat_name"
        )

        st.text_input(
            "Skipper name",
            value=boat_data.get("skipper_name", "x"),
            key="skipper_name"
        )

        st.divider()

        st.number_input(
            "Heading (°)",
            min_value=0.0,
            max_value=359.0,
            value=float(boat_data.get("heading_target", 0)),
            step=1.0,
            key="heading_target"
        )

        tack = boat_data.get("tack", "port")

        if tack not in ["port", "starboard"]:
            tack = "port"

        st.selectbox(
            "Tack",
            options=["port", "starboard"],
            index=["port", "starboard"].index(tack),
            key="tack"
        )

        st.divider()

        # =====================================================
        # 8. NAVIGATION INFORMATION
        # =====================================================

        st.subheader("Navigation")

        st.metric(
            "True heading",
            f"{heading:.1f}°"
        )

        st.metric(
            "True speed",
            f"{speed_knots:.2f} knots"
        )

        # =====================================================
        # 9. LAST IMPORTANT EVENT
        # =====================================================

        st.divider()

        st.subheader("Information")

        st.info(
            boat_data.get(
                "information",
                "Welcome on board"
            )
        )

        # =====================================================
        # 10. WINDY LINK
        # =====================================================

        windy_url = (
            f"https://www.windy.com/{latitude}/{longitude}"
            f"?{latitude},{longitude},11"
        )

        st.link_button(
            "Windy forecast",
            windy_url,
            use_container_width=True
        )


BoatData = GetLastBoat()

newTime= (datetime.fromisoformat(BoatData["last_update_time"])+timedelta(seconds=10)).isoformat()
waypoints=GetWaypoint()

BoatData["tack"]="port"
wind_speed,wind_direction=GetWind(BoatData["latitude"],BoatData["longitude"])
BoatData["wind_speed"]=wind_speed
BoatData["wind_direction"]=wind_direction
current_speed,current_direction=GetCurrent(BoatData["latitude"],BoatData["longitude"])
BoatData["current_speed"]=current_speed
BoatData["current_direction"]=current_direction
AisData= GetAisData(BoatData["latitude"],BoatData["longitude"])
BoatData, AisData=SimulateMovement(datetime.now(timezone.utc).isoformat(), BoatData, AisData)
colision=CheckColision(BoatData, AisData)
waypoint=CheckWaypoint(BoatData["latitude"],BoatData["longitude"],waypoints)

DrawInterface(BoatData, AisData)