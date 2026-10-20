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
    st.warning("Could not load AIS data")

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
