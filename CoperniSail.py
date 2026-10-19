from datetime import datetime, timezone, timedelta
import json
import math
import os
import copernicusmarine
from firebase_admin import credentials, firestore
import firebase_admin
import numpy as np
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(layout="wide")

# 1. Initialize Firestore Database Client
@st.cache_resource
def get_firestore_client():
  if not firebase_admin._apps:
    # Supports secrets stored either under a [Firestore] section or at the root of st.secrets
    secret_source = st.secrets.get("Firestore", st.secrets)
    cred_dict = dict(secret_source)

    # Ensure private key newline formatting is correct if loaded from string escape
    if "private_key" in cred_dict:
      cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")

    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
  return firestore.client()


db = get_firestore_client()
STATE_DOC_REF = db.collection("sim_state").document("current")

# Default simulation state
default_state = {
    "SIM_LATITUDE": 51.0,
    "SIM_LONGITUDE": 1.5,
    "SIM_HEADING": 270,
    "SIM_SPEED": 0.0,
    "SIM_LENGTH": 25.0,
    "SIM_BEAM": 6.0,
    "SIM_LAST_UPDATE": datetime.now(timezone.utc).isoformat(),
}

# 2. Initialize Session State securely from Firestore
if "initialized" not in st.session_state:
  try:
    doc = STATE_DOC_REF.get()
    if doc.exists:
      saved_state = doc.to_dict()
      for k, v in saved_state.items():
        st.session_state[k] = v
  except Exception as e:
    st.warning(f"Could not load state from Firestore: {e}")
  st.session_state["initialized"] = True

# Ensure any missing keys get default values safely
for k, v in default_state.items():
  if k not in st.session_state:
    st.session_state[k] = v

if isinstance(st.session_state.get("SIM_LAST_UPDATE"), str):
  try:
    st.session_state["SIM_LAST_UPDATE"] = datetime.fromisoformat(
        st.session_state["SIM_LAST_UPDATE"]
    )
  except Exception:
    st.session_state["SIM_LAST_UPDATE"] = datetime.now(timezone.utc)

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


def create_boat_triangle(lat, lon, length_m, beam_m, course_deg):
  if not length_m or length_m <= 0:
    length_m = 20
  if not beam_m or beam_m <= 0:
    beam_m = length_m / 3.0
  if course_deg is None:
    course_deg = 0.0

  theta = math.radians(course_deg)
  meters_per_deg_lat = 111111.0
  meters_per_deg_lon = 111111.0 * math.cos(math.radians(lat))

  bow_m_lat = (length_m / 2.0) * math.cos(theta)
  bow_m_lon = (length_m / 2.0) * math.sin(theta)
  stern_m_lat = -(length_m / 2.0) * math.cos(theta)
  stern_m_lon = -(length_m / 2.0) * math.sin(theta)

  right_m_lat = -(beam_m / 2.0) * math.sin(theta)
  right_m_lon = (beam_m / 2.0) * math.cos(theta)

  bow_lat = lat + (bow_m_lat / meters_per_deg_lat)
  bow_lon = lon + (bow_m_lon / meters_per_deg_lon)

  port_lat = (
      lat
      + (stern_m_lat / meters_per_deg_lat)
      - (right_m_lat / meters_per_deg_lat)
  )
  port_lon = (
      lon
      + (stern_m_lon / meters_per_deg_lon)
      - (right_m_lon / meters_per_deg_lon)
  )

  stbd_lat = (
      lat
      + (stern_m_lat / meters_per_deg_lat)
      + (right_m_lat / meters_per_deg_lat)
  )
  stbd_lon = (
      lon
      + (stern_m_lon / meters_per_deg_lon)
      + (right_m_lon / meters_per_deg_lon)
  )

  return [[bow_lat, bow_lon], [port_lat, port_lon], [stbd_lat, stbd_lon]]


def estimate_current_position(lat, lon, sog, cog, timestamp_str):
  if lat is None or lon is None or sog is None or cog is None or not timestamp_str:
    return lat, lon
  try:
    clean_ts = timestamp_str.replace("Z", "+00:00")
    seen_time = datetime.fromisoformat(clean_ts)
    now = datetime.now(timezone.utc)
    elapsed_hours = max(0, (now - seen_time).total_seconds() / 3600.0)

    distance_nm = sog * elapsed_hours
    cog_rad = math.radians(cog)

    d_lat = (distance_nm * math.cos(cog_rad)) / 60.0
    d_lon = (distance_nm * math.sin(cog_rad)) / (
        60.0 * math.cos(math.radians(lat))
    )
    return lat + d_lat, lon + d_lon
  except Exception:
    return lat, lon


# 3. Wrap simulation, data fetching, and map rendering in a fragment running every 60 seconds
@st.fragment(run_every="60s")
def live_simulation_fragment():
  latitude = st.session_state.get("SIM_LATITUDE", 51.0)
  longitude = st.session_state.get("SIM_LONGITUDE", 1.5)
  current_time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

  # Fetch Ocean Currents
  try:
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
    eastward_velocity = point_data_curr["uo"].values
    northward_velocity = point_data_curr["vo"].values
  except Exception:
    eastward_velocity, northward_velocity = np.array([0.0]), np.array([0.0])

  # Fetch Wind Data
  query_time = datetime.now(timezone.utc)
  wind_time_str = query_time.strftime("%Y-%m-%d %H:%M:%S")
  try:
    ds_wind = copernicusmarine.open_dataset(
        dataset_id="cmems_obs-wind_glo_phy_nrt_l4_0.125deg_PT1H",
        minimum_latitude=latitude,
        maximum_latitude=latitude,
        minimum_longitude=longitude,
        maximum_longitude=longitude,
        start_datetime=wind_time_str,
        end_datetime=wind_time_str,
        variables=["eastward_wind", "northward_wind"],
    )
    point_data_wind = ds_wind.sel(
        latitude=latitude, longitude=longitude, method="nearest"
    )
    u = point_data_wind["eastward_wind"].values
    v = point_data_wind["northward_wind"].values
    wind_speed = np.sqrt(u**2 + v**2)
    wind_direction_from = (270 - np.degrees(np.arctan2(v, u))) % 360
  except Exception:
    wind_speed, wind_direction_from = np.array([5.0]), np.array([180.0])

  # Sailing Physics Update
  wind_dir = (
      wind_direction_from[0]
      if hasattr(wind_direction_from, "ndim") and wind_direction_from.ndim > 0
      else wind_direction_from
  )
  w_speed_ms = (
      wind_speed[0]
      if hasattr(wind_speed, "ndim") and wind_speed.ndim > 0
      else wind_speed
  )
  wind_speed_knots = w_speed_ms * 1.94384

  current_u_ms = (
      eastward_velocity[0]
      if hasattr(eastward_velocity, "ndim") and eastward_velocity.ndim > 0
      else eastward_velocity
  )
  current_v_ms = (
      northward_velocity[0]
      if hasattr(northward_velocity, "ndim") and northward_velocity.ndim > 0
      else northward_velocity
  )
  current_u_knots = current_u_ms * 1.94384
  current_v_knots = current_v_ms * 1.94384

  sim_heading = st.session_state.get("SIM_HEADING", 270)
  angle_diff = abs(sim_heading - wind_dir) % 360
  if angle_diff > 180:
    angle_diff = 360 - angle_diff

  if angle_diff <= 45.0:
    st.session_state["SIM_SPEED"] = 0.0
  else:
    st.session_state["SIM_SPEED"] = min(wind_speed_knots / 2.0, 5.0)

  heading_rad = math.radians(sim_heading)
  boat_u_knots = st.session_state["SIM_SPEED"] * math.sin(heading_rad)
  boat_v_knots = st.session_state["SIM_SPEED"] * math.cos(heading_rad)

  total_u_knots = boat_u_knots + current_u_knots
  total_v_knots = boat_v_knots + current_v_knots

  sog_knots = math.sqrt(total_u_knots**2 + total_v_knots**2)
  cog_degrees = math.degrees(math.atan2(total_u_knots, total_v_knots)) % 360

  now = datetime.now(timezone.utc)
  last_update = st.session_state.get("SIM_LAST_UPDATE", now)
  elapsed_seconds = (now - last_update).total_seconds()
  elapsed_hours = elapsed_seconds / 3600.0

  if elapsed_hours > 0 and sog_knots > 0:
    distance_nm = sog_knots * elapsed_hours
    cog_rad = math.radians(cog_degrees)
    delta_lat = (distance_nm * math.cos(cog_rad)) / 60.0
    delta_lon = (distance_nm * math.sin(cog_rad)) / (
        60.0 * math.cos(math.radians(latitude))
    )
    st.session_state["SIM_LATITUDE"] = latitude + delta_lat
    st.session_state["SIM_LONGITUDE"] = longitude + delta_lon

  st.session_state["SIM_LAST_UPDATE"] = now

  # Persist State to Firestore
  state_to_save = {
      "SIM_LATITUDE": float(st.session_state.get("SIM_LATITUDE", 51.0)),
      "SIM_LONGITUDE": float(st.session_state.get("SIM_LONGITUDE", 1.5)),
      "SIM_HEADING": int(st.session_state.get("SIM_HEADING", 270)),
      "SIM_SPEED": float(st.session_state.get("SIM_SPEED", 0.0)),
      "SIM_LENGTH": float(st.session_state.get("SIM_LENGTH", 25.0)),
      "SIM_BEAM": float(st.session_state.get("SIM_BEAM", 6.0)),
      "SIM_LAST_UPDATE": now.isoformat(),
  }
  try:
    STATE_DOC_REF.set(state_to_save)
  except Exception as e:
    st.error(f"Failed to save state to Firestore: {e}")

  # Fetch AIS Vessels
  radius_nm = 10
  lat_offset = radius_nm / 60.0
  lon_offset = radius_nm / (
      60.0 * math.cos(math.radians(st.session_state["SIM_LATITUDE"]))
  )
  min_lat = st.session_state["SIM_LATITUDE"] - lat_offset
  max_lat = st.session_state["SIM_LATITUDE"] + lat_offset
  min_lon = st.session_state["SIM_LONGITUDE"] - lon_offset
  max_lon = st.session_state["SIM_LONGITUDE"] + lon_offset

  ais_url = f"https://ais.openwaters.io/v1/vessels?bbox={min_lat},{min_lon},{max_lat},{max_lon}"
  geo_data = None
  try:
    resp = requests.get(ais_url)
    resp.raise_for_status()
    geo_data = resp.json()
  except Exception:
    pass

  # Build Folium Map
  m = folium.Map(
      location=[
          st.session_state["SIM_LATITUDE"],
          st.session_state["SIM_LONGITUDE"],
      ],
      zoom_start=11,
      tiles=None,
  )
  folium.TileLayer(
      tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      attr="Tiles &copy; Esri",
      name="Esri Satellite",
  ).add_to(m)

  folium.Circle(
      location=[
          st.session_state["SIM_LATITUDE"],
          st.session_state["SIM_LONGITUDE"],
      ],
      radius=radius_nm * 1852,
      color="cyan",
      fill=True,
      fill_opacity=0.03,
  ).add_to(m)

  # Plot Simulated Boat
  my_triangle = create_boat_triangle(
      st.session_state["SIM_LATITUDE"],
      st.session_state["SIM_LONGITUDE"],
      st.session_state.get("SIM_LENGTH", 25.0),
      st.session_state.get("SIM_BEAM", 6.0),
      st.session_state.get("SIM_HEADING", 270),
  )
  folium.Polygon(
      locations=my_triangle,
      color="#8e44ad",
      weight=3,
      fill=True,
      fill_color="#9b59b6",
      fill_opacity=0.9,
      tooltip="My Simulated Boat",
  ).add_to(m)

  # Plot AIS Vessels
  if geo_data and "features" in geo_data:
    for vessel in geo_data["features"]:
      props = vessel.get("properties", {})
      coords = vessel.get("geometry", {}).get("coordinates", [None, None])
      if coords[0] is None or coords[1] is None:
        continue
      est_lat, est_lon = estimate_current_position(
          coords[1],
          coords[0],
          props.get("sog", 0),
          props.get("cog", 0),
          props.get("seen"),
      )
      triangle_coords = create_boat_triangle(
          est_lat,
          est_lon,
          props.get("length", 20),
          props.get("width", None),
          props.get("cog", 0),
      )
      folium.Polygon(
          locations=triangle_coords,
          color="#f39c12",
          weight=2,
          fill=True,
          fill_color="#f1c40f",
          fill_opacity=0.8,
      ).add_to(m)

  st.caption(
      f"Last auto-refresh: {now.strftime('%H:%M:%S')} UTC | Position:"
      f" {st.session_state['SIM_LATITUDE']:.5f}°N,"
      f" {st.session_state['SIM_LONGITUDE']:.5f}°E"
  )

  # Pass returned_objects=[] to prevent infinite loop re-renders
  st_folium(m, width=1200, height=650, key="live_map", returned_objects=[])


# Execute the live updating fragment
live_simulation_fragment()
