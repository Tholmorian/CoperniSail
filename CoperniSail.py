"""CoperniSail - sail a dinghy from France to England in real time.

Entry point for Streamlit:  streamlit run CoperniSail.py
Secrets (.streamlit/secrets.toml): [Firestore], [CopernicusMarine], [KeyTester]
"""
import json
import math
import os
import random
import time
from datetime import datetime, timedelta, timezone

import folium
import numpy as np
import pandas as pd
import requests
import streamlit as st
from google.cloud import firestore
from shapely.geometry import Polygon
from streamlit_folium import st_folium

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
UPDATE_PERIOD = 60          # s, UI / main loop period
STALE_BOAT = 300            # s, other boats are updated if older than this
METEO_PERIOD = 600          # s, wind/current refresh period
MAX_SIM_AGE = 900           # s, older positions are not simulated
SIM_STEP = 10               # s, simulation step
MAX_OTHER_BOATS = 10        # max other boats updated per cycle
KNOT = 0.514444             # m/s
MAX_BOAT_SPEED = 5 * KNOT   # m/s
BOAT_LENGTH = 6.0           # m, length of a player's dinghy
NM = 1852.0                 # m
M_PER_DEG = 111320.0
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

# Verify these two against the real services (see notes in the chat answer)
CMEMS_DATASET = "cmems_mod_nws_phy-uv_anfc_0.027deg_PT15M-i"
AIS_URL = "https://ais.openwaters.io/api/vessels"

DEFAULT_WAYPOINTS = [
    {"number": 1, "latitude": 50.97, "longitude": 1.87, "radius": 0.5},
    {"number": 2, "latitude": 51.11, "longitude": 1.31, "radius": 0.5},
]


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def _now():
    return datetime.now(timezone.utc)


def _parse(t):
    dt = t if isinstance(t, datetime) else datetime.fromisoformat(t)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _angdiff(a, b):
    return abs((a - b + 180) % 360 - 180)


def _dist_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(a))


def _move(lat, lon, north_m, east_m):
    new_lat = lat + north_m / M_PER_DEG
    new_lon = lon + east_m / (M_PER_DEG * max(math.cos(math.radians(lat)), 1e-6))
    return new_lat, new_lon


# ----------------------------------------------------------------------------
# Keys
# ----------------------------------------------------------------------------
def _shifts():
    secret = str(st.secrets["KeyTester"]["secret_key"])
    return [ord(c) % 36 for c in secret] or [0]


def _encode(chars, shifts):
    return "".join(
        ALPHABET[(ALPHABET.index(c) + shifts[i % len(shifts)]) % 36]
        for i, c in enumerate(chars)
    )


def GenerateKey():
    """8 random chars, encoded with the KeyTester secret, interlaced (16 chars)."""
    rng = random.SystemRandom()
    rand = "".join(rng.choice(ALPHABET) for _ in range(8))
    enc = _encode(rand, _shifts())
    return "".join(r + e for r, e in zip(rand, enc))


def ValidKey(key):
    if not key or len(key) != 16 or any(c not in ALPHABET for c in key):
        return False
    return _encode(key[0::2], _shifts()) == key[1::2]


# ----------------------------------------------------------------------------
# Database (Firestore: collection 'sim_state', document 'current', field 'boats')
# ----------------------------------------------------------------------------
@st.cache_resource
def _db():
    return firestore.Client.from_service_account_info(dict(st.secrets["Firestore"]))


def _doc():
    return _db().collection("sim_state").document("current")


def _all_boats():
    snap = _doc().get()
    return (snap.to_dict() or {}).get("boats", {}) if snap.exists else {}


def _save(key, fields):
    _doc().set({"boats": {key: fields}}, merge=True)


def GetMyBoat(key):
    return _all_boats().get(key)


def GetLastBoat(exclude=()):
    """Boat with the oldest last_update_time (optionally excluding some keys)."""
    boats = [b for k, b in _all_boats().items() if k not in exclude]
    if not boats:
        return None
    return min(boats, key=lambda b: _parse(b["last_update_time"]))


def MakeBoat(key, waypoints):
    now = _now()
    i = waypoints["number"].index(1)
    boat = {
        "boat_key": key,
        "boat_name": "x",
        "skipper_name": "x",
        "last_update_time": now.isoformat(),
        "latitude": waypoints["latitude"][i],
        "longitude": waypoints["longitude"][i],
        "heading": 0,
        "heading_target": 0,
        "true_heading": 0,
        "tack": "stopped",
        "min_wind_angle": 50,
        "max_wind_angle": 180,
        "speed": 0,
        "best_time_to_arrival": 0,
        "start_time": now.isoformat(),
        "meteo_update_time": (now - timedelta(hours=1)).isoformat(),
        "wind_speed": 0,
        "wind_direction": 0,
        "current_speed": 0,
        "current_direction": 0,
        "information": "Welcome on board",
        "last_waypoint": 0,
    }
    _save(key, boat)
    return boat


# ----------------------------------------------------------------------------
# Waypoints
# ----------------------------------------------------------------------------
def GetWaypoint():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "waypoints.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)
    except Exception:
        items = DEFAULT_WAYPOINTS
    items = sorted(items, key=lambda w: w["number"])
    return {k: [w[k] for w in items] for k in ("number", "latitude", "longitude", "radius")}


def CheckWaypoint(latitude, longitude, waypoints):
    """0 if not in a zone, else the waypoint number (highest if several)."""
    found = 0
    for n, la, lo, r in zip(waypoints["number"], waypoints["latitude"],
                            waypoints["longitude"], waypoints["radius"]):
        if _dist_m(latitude, longitude, la, lo) <= r * NM:
            found = max(found, n)
    return found


# ----------------------------------------------------------------------------
# External data
# ----------------------------------------------------------------------------
def GetWind(latitude, longitude):
    """Open-Meteo wind -> {'northward','eastward'} in m/s (direction the wind blows to)."""
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": latitude, "longitude": longitude,
                    "current": "wind_speed_10m,wind_direction_10m",
                    "wind_speed_unit": "ms"},
            timeout=15,
        )
        r.raise_for_status()
        cur = r.json()["current"]
        speed, d_from = float(cur["wind_speed_10m"]), math.radians(float(cur["wind_direction_10m"]))
        return {"northward": -speed * math.cos(d_from), "eastward": -speed * math.sin(d_from)}
    except Exception:
        return {"northward": 0.0, "eastward": 0.0}


def GetCurrent(latitude, longitude):
    """Copernicus Marine surface current -> {'northward','eastward'} in m/s."""
    try:
        import copernicusmarine
        cm = st.secrets["CopernicusMarine"]
        ds = copernicusmarine.open_dataset(
            dataset_id=CMEMS_DATASET,
            variables=["uo", "vo"],
            username=cm["username"],
            password=cm["password"],
            minimum_longitude=longitude - 0.2, maximum_longitude=longitude + 0.2,
            minimum_latitude=latitude - 0.2, maximum_latitude=latitude + 0.2,
        )
        if "depth" in ds.dims:
            ds = ds.isel(depth=0)
        t = np.datetime64(_now().replace(tzinfo=None))
        pt = ds.sel(latitude=latitude, longitude=longitude, time=t, method="nearest")
        return {"northward": float(np.nan_to_num(pt["vo"].values)),
                "eastward": float(np.nan_to_num(pt["uo"].values))}
    except Exception:
        return {"northward": 0.0, "eastward": 0.0}


def GetAisData(latitude, longitude):
    """Vessels within 5 Nm. Returns a list of dicts:
    Name, Length (m), Speed (m/s), Heading (deg), UpdateTime (ISO), latitude, longitude."""
    try:
        dlat = 5 * NM / M_PER_DEG
        dlon = dlat / max(math.cos(math.radians(latitude)), 1e-6)
        r = requests.get(
            AIS_URL,
            params={"lamin": latitude - dlat, "lamax": latitude + dlat,
                    "lomin": longitude - dlon, "lomax": longitude + dlon},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        items = data if isinstance(data, list) else (data.get("vessels") or data.get("data") or [])
        out = []
        for it in items:
            lat = it.get("latitude", it.get("lat"))
            lon = it.get("longitude", it.get("lon", it.get("lng")))
            if lat is None or lon is None:
                continue
            lat, lon = float(lat), float(lon)
            if _dist_m(latitude, longitude, lat, lon) > 5 * NM:
                continue
            heading = it.get("heading", it.get("cog", 0)) or 0
            if heading == 511:          # AIS "not available"
                heading = it.get("cog", 0) or 0
            out.append({
                "Name": str(it.get("name", it.get("shipname", "unknown"))),
                "Length": float(it.get("length", 0) or 20),
                "Speed": float(it.get("speed", it.get("sog", 0)) or 0) * KNOT,
                "Heading": float(heading),
                "UpdateTime": str(it.get("time", it.get("timestamp", _now().isoformat()))),
                "latitude": lat,
                "longitude": lon,
            })
        return out
    except Exception:
        return []


# ----------------------------------------------------------------------------
# Simulation
# ----------------------------------------------------------------------------
def _constrained_heading(target, tack, wind_from, amin, amax):
    """Closest heading to target on the given tack with amin <= wind angle <= amax."""
    amin = max(0.0, min(180.0, amin))
    amax = max(amin, min(180.0, amax))
    s = -1 if tack == "starboard" else 1   # starboard: heading = wind_from - a
    raw = ((wind_from - target) if tack == "starboard" else (target - wind_from)) % 360
    if amin <= raw <= amax:
        a = raw
    else:
        a = min((amin, amax), key=lambda x: _angdiff((wind_from + s * x) % 360, target))
    return (wind_from + s * a) % 360


def SimulateMovement(time_, boat_data, AIS_data):
    """Move the boat and the AIS boats (straight line) up to time_. Mutates and returns both."""
    t_end = _parse(time_)

    # --- player's boat
    dt = (t_end - _parse(boat_data["last_update_time"])).total_seconds()
    if boat_data["tack"] == "stopped":
        boat_data["speed"] = 0.0          # at anchor
    elif dt > 0:
        h = _constrained_heading(boat_data["heading_target"], boat_data["tack"],
                                 boat_data["wind_direction"],
                                 boat_data["min_wind_angle"], boat_data["max_wind_angle"])
        stw = min(0.5 * boat_data["wind_speed"], MAX_BOAT_SPEED)
        cd = math.radians(boat_data["current_direction"])
        hr = math.radians(h)
        vn = stw * math.cos(hr) + boat_data["current_speed"] * math.cos(cd)
        ve = stw * math.sin(hr) + boat_data["current_speed"] * math.sin(cd)
        boat_data["latitude"], boat_data["longitude"] = _move(
            boat_data["latitude"], boat_data["longitude"], vn * dt, ve * dt)
        boat_data["heading"] = h
        boat_data["true_heading"] = math.degrees(math.atan2(ve, vn)) % 360
        boat_data["speed"] = math.hypot(vn, ve)
    boat_data["last_update_time"] = t_end.isoformat()

    # --- AIS boats
    for b in AIS_data:
        d = (t_end - _parse(b["UpdateTime"])).total_seconds()
        if d > 0:
            hr = math.radians(b["Heading"])
            b["latitude"], b["longitude"] = _move(
                b["latitude"], b["longitude"],
                b["Speed"] * math.cos(hr) * d, b["Speed"] * math.sin(hr) * d)
        b["UpdateTime"] = t_end.isoformat()
    return boat_data, AIS_data


def DrawBoatTriangle(latitude, longitude, length, heading):
    """Triangle centred on the boat, width = length/3. Returns {'latitude':[3],'longitude':[3]}."""
    half, w = length / 2.0, length / 3.0
    pts = [(half, 0.0), (-half, -w / 2), (-half, w / 2)]    # (forward, right)
    h = math.radians(heading)
    lats, lons = [], []
    for f, r in pts:
        north = f * math.cos(h) - r * math.sin(h)
        east = f * math.sin(h) + r * math.cos(h)
        la, lo = _move(latitude, longitude, north, east)
        lats.append(la)
        lons.append(lo)
    return {"latitude": lats, "longitude": lons}


def _polygon(tri):
    return Polygon(list(zip(tri["longitude"], tri["latitude"])))


def CheckColision(boat_data, AIS_data):
    """Returns the AIS boat colliding with the player's boat, else []."""
    me = _polygon(DrawBoatTriangle(boat_data["latitude"], boat_data["longitude"],
                                   BOAT_LENGTH, boat_data["heading"]))
    for b in AIS_data:
        if _dist_m(boat_data["latitude"], boat_data["longitude"],
                   b["latitude"], b["longitude"]) > 1000:
            continue
        other = _polygon(DrawBoatTriangle(b["latitude"], b["longitude"],
                                          b["Length"], b["Heading"]))
        if me.intersects(other):
            return b
    return []


@st.cache_resource
def _landmask():
    from roaring_landmask import RoaringLandmask
    return RoaringLandmask.new()


def CheckAground(latitude, longitude):
    try:
        mask = _landmask()
        try:
            return bool(mask.contains(longitude, latitude))
        except Exception:
            return bool(mask.contains_many_par(np.array([longitude]), np.array([latitude]))[0])
    except Exception:
        return False


# ----------------------------------------------------------------------------
# Boat update process
# ----------------------------------------------------------------------------
def _reset_to_start(boat, waypoints, t):
    i = waypoints["number"].index(1)
    boat.update({
        "latitude": waypoints["latitude"][i], "longitude": waypoints["longitude"][i],
        "tack": "stopped", "speed": 0.0, "last_waypoint": 0, "start_time": t.isoformat(),
    })


def UpdateBoat(boat, is_mine, user_input, waypoints):
    """One update cycle for a boat. Returns (boat, ais_list)."""
    key = boat["boat_key"]
    now = _now()
    t_prev = _parse(boat["last_update_time"])
    _save(key, {"last_update_time": now.isoformat()})     # claim: others skip this boat

    if is_mine and user_input:
        for f in ("boat_name", "skipper_name", "heading_target", "tack",
                  "min_wind_angle", "max_wind_angle"):
            if user_input.get(f) not in ("", None):
                boat[f] = user_input[f]

    # Meteo
    if (now - _parse(boat["meteo_update_time"])).total_seconds() > METEO_PERIOD:
        w = GetWind(boat["latitude"], boat["longitude"])
        c = GetCurrent(boat["latitude"], boat["longitude"])
        boat["wind_speed"] = math.hypot(w["eastward"], w["northward"])
        boat["wind_direction"] = math.degrees(math.atan2(-w["eastward"], -w["northward"])) % 360
        boat["current_speed"] = math.hypot(c["eastward"], c["northward"])
        boat["current_direction"] = math.degrees(math.atan2(c["eastward"], c["northward"])) % 360
        boat["meteo_update_time"] = now.isoformat()

    ais = GetAisData(boat["latitude"], boat["longitude"])
    info = None
    last_wp = waypoints["number"][-1]

    if (now - t_prev).total_seconds() <= MAX_SIM_AGE:
        boat["last_update_time"] = t_prev.isoformat()
        t = t_prev
        while t < now:
            t = min(t + timedelta(seconds=SIM_STEP), now)
            SimulateMovement(t, boat, ais)

            hit = CheckColision(boat, ais)
            if hit:
                _reset_to_start(boat, waypoints, t)
                info = f"Collision with {hit['Name']}! Back to start."
                break

            wp = CheckWaypoint(boat["latitude"], boat["longitude"], waypoints)
            if wp != 1 and boat["speed"] > 0 and CheckAground(boat["latitude"], boat["longitude"]):
                _reset_to_start(boat, waypoints, t)
                info = "You ran aground! Back to start."
                break

            if wp == 1:
                boat["start_time"] = t.isoformat()
                boat["last_waypoint"] = 1
            elif wp == last_wp:
                duration = (t - _parse(boat["start_time"])).total_seconds()
                best = boat["best_time_to_arrival"]
                if best <= 0 or duration < best:
                    boat["best_time_to_arrival"] = duration
                    info = f"Arrived in {timedelta(seconds=int(duration))} - new personal best!"
                else:
                    info = f"Arrived in {timedelta(seconds=int(duration))}."
                _reset_to_start(boat, waypoints, t)
                break
            elif wp > 1:
                boat["last_waypoint"] = wp
                info = f"Waypoint {wp} passed."

    boat["last_update_time"] = now.isoformat()
    if info:
        boat["information"] = info
    _save(key, boat)
    return boat, ais


# ----------------------------------------------------------------------------
# User interface
# ----------------------------------------------------------------------------
def _init_state():
    for k, v in {"boat_key": "", "boat_name": "", "skipper_name": "", "heading_target": 0,
                 "tack": "stopped", "min_wind_angle": 50, "max_wind_angle": 180,
                 "show_hof": False, "map_counter": 0}.items():
        st.session_state.setdefault(k, v)


def _sync_from_boat(boat):
    """Fill the widgets with the boat's stored values (before widgets are created)."""
    st.session_state.update({
        "boat_name": boat["boat_name"] if boat["boat_name"] != "x" else "",
        "skipper_name": boat["skipper_name"] if boat["skipper_name"] != "x" else "",
        "heading_target": int(boat["heading_target"]) % 360,
        "tack": boat["tack"],
        "min_wind_angle": int(boat["min_wind_angle"]),
        "max_wind_angle": int(boat["max_wind_angle"]),
    })


def DrawControls():
    """Create the page layout and the editable fields once. Returns the placeholders."""
    col_map, col_ctrl = st.columns([3, 1])
    with col_ctrl:
        st.text_input("Boat key", key="boat_key")
        st.text_input("Boat name", key="boat_name")
        st.text_input("Skipper name", key="skipper_name")
        st.number_input("Heading (°)", min_value=0, max_value=359, step=1, key="heading_target")
        st.selectbox("Tack", ["stopped", "port", "starboard"], key="tack")
        st.number_input("Min wind angle (°)", min_value=0, max_value=180, step=1, key="min_wind_angle")
        st.number_input("Max wind angle (°)", min_value=0, max_value=180, step=1, key="max_wind_angle")
        ui = {"map": col_map.empty(), "gps": st.empty(), "info": st.empty(), "windy": st.empty()}
        st.toggle("Hall of fame", key="show_hof")
    ui["hof"] = st.empty()
    return ui


def GetUserInput():
    s = st.session_state
    return {
        "boat_key": str(s["boat_key"]).strip().upper(),
        "boat_name": str(s["boat_name"]).strip(),
        "skipper_name": str(s["skipper_name"]).strip(),
        "heading_target": int(s["heading_target"]),
        "tack": s["tack"],
        "min_wind_angle": int(s["min_wind_angle"]),
        "max_wind_angle": int(s["max_wind_angle"]),
    }


def DrawInterface(boat_data, AIS_data, ui, waypoints):
    lat, lon = boat_data["latitude"], boat_data["longitude"]
    m = folium.Map(location=[lat, lon], zoom_start=11, tiles=None, control_scale=True)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri",
        name="Esri Satellite",
    ).add_to(m)

    for n, la, lo, r in zip(waypoints["number"], waypoints["latitude"],
                            waypoints["longitude"], waypoints["radius"]):
        folium.Circle([la, lo], radius=r * NM, color="yellow", weight=2,
                      fill=False, tooltip=f"Waypoint {n}").add_to(m)

    # 5 Nm circle with a line every 10 degrees
    folium.Circle([lat, lon], radius=5 * NM, color="white", weight=1, fill=False).add_to(m)
    for deg in range(0, 360, 10):
        end = _move(lat, lon, 5 * NM * math.cos(math.radians(deg)),
                    5 * NM * math.sin(math.radians(deg)))
        folium.PolyLine([[lat, lon], list(end)], color="white", weight=1, opacity=0.5).add_to(m)

    for b in AIS_data:
        tri = DrawBoatTriangle(b["latitude"], b["longitude"], b["Length"], b["Heading"])
        folium.Polygon(
            list(zip(tri["latitude"], tri["longitude"])), color="red", fill=True, fill_opacity=0.8,
            tooltip=f"{b['Name']} - {b['Length']:.0f} m - {b['Speed'] / KNOT:.1f} kn",
        ).add_to(m)

    tri = DrawBoatTriangle(lat, lon, BOAT_LENGTH, boat_data["heading"])
    folium.Polygon(list(zip(tri["latitude"], tri["longitude"])), color="cyan",
                   fill=True, fill_opacity=1).add_to(m)
    folium.CircleMarker([lat, lon], radius=5, color="cyan", fill=False,
                        tooltip=boat_data["boat_name"]).add_to(m)  # visible at low zoom

    st.session_state["map_counter"] += 1
    with ui["map"].container():
        st_folium(m, height=620, use_container_width=True, returned_objects=[],
                  key=f"map_{st.session_state['map_counter']}")

    ui["gps"].markdown(
        f"**True heading:** {boat_data['true_heading']:.0f}°  \n"
        f"**Speed:** {boat_data['speed'] / KNOT:.1f} kn  \n"
        f"**Wind:** {boat_data['wind_speed'] / KNOT:.1f} kn from {boat_data['wind_direction']:.0f}°"
    )
    ui["info"].info(boat_data["information"])
    ui["windy"].markdown(
        f"[Windy forecast](https://www.windy.com/{lat:.3f}/{lon:.3f}?{lat:.3f},{lon:.3f},9)")


def DrawHallOfFame(ui, my_key):
    if not st.session_state.get("show_hof"):
        ui["hof"].empty()
        return
    boats = [b for b in _all_boats().values() if b.get("best_time_to_arrival", 0) > 0]
    boats.sort(key=lambda b: b["best_time_to_arrival"])
    rows = [{"Rank": i + 1, "Boat": b["boat_name"], "Skipper": b["skipper_name"],
             "Best time": str(timedelta(seconds=int(b["best_time_to_arrival"])))}
            for i, b in enumerate(boats[:20])]
    my_rank = next((i + 1 for i, b in enumerate(boats) if b["boat_key"] == my_key), None)
    with ui["hof"].container():
        st.subheader("Hall of fame - best 20 times")
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        else:
            st.write("No arrival yet.")
        if my_rank:
            st.write(f"Your position: **{my_rank}** / {len(boats)}")


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="CoperniSail", page_icon="⛵", layout="wide")
    st.title("⛵ CoperniSail")
    waypoints = GetWaypoint()
    _init_state()

    key = str(st.session_state["boat_key"]).strip().upper()
    valid = ValidKey(key)
    if valid and st.session_state.get("synced_key") != key:
        boat = GetMyBoat(key) or MakeBoat(key, waypoints)
        _sync_from_boat(boat)                 # must happen before the widgets exist
        st.session_state["synced_key"] = key

    ui = DrawControls()
    if not key:
        st.info("Type your boat key to start. Ask the webmaster for a key.")
        st.stop()
    if not valid:
        st.error("This boat key is not valid. Ask the webmaster for a valid key.")
        st.stop()

    while True:
        user_input = GetUserInput()
        boat = GetMyBoat(key) or MakeBoat(key, waypoints)
        boat, ais = UpdateBoat(boat, True, user_input, waypoints)
        DrawInterface(boat, ais, ui, waypoints)
        DrawHallOfFame(ui, key)

        done = {key}
        for _ in range(MAX_OTHER_BOATS):
            other = GetLastBoat(exclude=done)
            if other is None or (_now() - _parse(other["last_update_time"])).total_seconds() < STALE_BOAT:
                break
            UpdateBoat(other, False, None, waypoints)
            done.add(other["boat_key"])

        time.sleep(UPDATE_PERIOD)


if __name__ == "__main__":
    main()
