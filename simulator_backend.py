import json
import os
from datetime import datetime, timezone

STATE_FILE = "sim_state.json"

# Default state if file doesn't exist
default_state = {
    "SIM_LATITUDE": 51.0,
    "SIM_LONGITUDE": 1.5,
    "SIM_HEADING": 270,
    "SIM_SPEED": 5.0,
    "SIM_LAST_UPDATE": datetime.now(timezone.utc).isoformat()
}

# Load existing state or fallback to default
if os.path.exists(STATE_FILE):
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
    except Exception:
        state = default_state
else:
    state = default_state

# Simulate a small movement northwards (adds 0.01 to latitude)
state["SIM_LATITUDE"] = round(state["SIM_LATITUDE"] + 0.01, 5)
state["SIM_LAST_UPDATE"] = datetime.now(timezone.utc).isoformat()

# Save back to JSON file
with open(STATE_FILE, "w") as f:
    json.dump(state, f, indent=4)

print(f"Test update successful! New Latitude: {state['SIM_LATITUDE']}")
