# Scope
This document describes the structure, functions and working process of the CoperniSail app.
# App description
The CoperniSail app is a game that let you sail a sailing dinghy from France to England. The aim is to reach an English port as fast as possible without being crushed by one of the big boats travelling in the channel. The app works in real time. It gather the real wind and current from the copernicusmarine API. It retreive the real boats positions from AIS data on the web. The user sees its boat and the other boats on a chart. It can configure the boat to follow a constant heading or a constant wind angle.
# Hosting
The database is hosted in my google cloud account, in a Firestore database. It contains boat positions and heading.
The code is ran on Streamlit could platform at the address https://copernisail.streamlit.app/ .
# Connections
The current data are retreived from copernicusmarine API with my username and password.
The wind data are retrieved from api.open-meteo.com without account.
The AIS boat positions are retreived from ais.openwaters.io website without account.

# General app process
When the app is loaded, the boat key field is empty. If a valid key is typed, the boat data are loaded in the database. If the key does not exist in the database it is created. If the key is not valid, the user is informed. To get a valid key the user shall ask it to the Webmaster. A key validity is tested by a function described below.
When a boat is loaded, the app updates every 60s.
The updating process is done for the user's boat then its user interface is updated. Then the updating process is done for the other boats that have not been updated from more than 5min.
The updating process consists in these steps: Load the boat data in the database. Update the last update time in the database so that other users do not try to update the boat data. Load the current at the boat position. Load the wind at the boat position. Load the surrouning boat AIS data. Simulate the boat movement and the surrounding boats movements to check for collisions. Check if the boat is arrived at the race goal. Update the boat position in the database.
Only if the process is applied to my boat: Load the heading set by the user on the user interface. Update my boat heading in the database. Update the user map.
When a colision is detected, the boat is set at the default start position.
When the boat arrives at the arrival, the travel time is saved in the hall of fame (in the database) and the boat is set at the default start position.
# Database description
The database data contains all the following fields for each entry:
- boat_key: Secret ID of the boat, known by the webmaster and the owner.
- boat_name: Name of the boat
- skipper_name: Name of the skipper
- last_update_time: Time of last update of boat data in UTC iso format
- latitude: latitude of the boat in decimal degree at the last update time
- longitude: longitude of the boat in decimal degree at the last update time
- heading: heading of the boat relative to true north, relative to water, not heading over ground, at the time of last update
- wind_angle: heading relative to true wind angle, at the time of last update
- follow_wind: true if the boat navigates at constant wind angle, false if it navigates at constant heading
- speed: speed in knots relative to ground at the time of last update
- best_time_to_arrival: duration in second of the best race time of the boat
- start_time: Time when starting race in UTC iso format
- meteo_update_time: Time when meteo of the boat has last been updated in UTC iso format
- wind_speed: Wind speed at boat position in m/s
- wind_direction: Wind direction at boat position in degree
- current_speed: Current speed at boat position in m/s
- current_direction: Current direction at boat position in degree
The database login data are stored in the secrets file of the Streamlit cloud. 

# Functions descriptions

## CoperniSail
The CoperniSail script file is the entry point of the app called by Streamlit when a user connect. It loops every 60s. In each loop, it loops through all boats in the database, starting by the boat which has the boat key indicated in the boat key field. It follows by the boat that has the oldest update time and repeat until every update time is more recent than 5min. The loop content is described hereunder:
- If the boat do not exist and the key is valid as tested by function ValidKey, create a new boat with function MakeBoat.
- Update in database last_update_time for the boat to prevent update by another user
- If meteo is older than 10min, update meteo data with function GetWind and function GetCurrent. Keep values to update all boat data in database at once.
- Load AIS data with function GetAisData.
- If the simulated boat is my boat, get heading and follow_wind from user interface with function GetUserInput.
- Simulate the boats displacement from last_update_time to now to detect colisions by looping by 10s step with function SimulateMovement. If position is older than 15min, do not simulate, update last_update_time only. Keep new boat position.
- If a colision has been detected, reset boat position.
- If the boat is aground, reset boat position.
- If the boat is in the start zone, update start_time.
- If the boat is in the arrival zone, update best_time_to_arrival if applicable.
- Save boat data in the database.
- If the simulated boat is my boat, update map.
## ValidKey
The function ValidKey(boolean key) returns true if the key is valid. It uses the secret [KeyTester] secret_key. It compares the last 8 characters to the encoding of the first 8 characters.
## GetMyBoat
the function GetMyBoat(key) Query the data of the boat with key in the Firestore database. Use the secrets in [Firestore] to login.
## GetLastBoat
The function GetLastBoat() Query the data of the boat with the oldest last_update_time in the Firestore database. Use the secrets under [Firestore] to login. It returns a dictionnary with the boat data.
## Makeboat
The function Makeboat(key) creates a boat in the database with default values.
## GetWind
The function GetWind(latitude,longitude) returns the a dictionnary with northward wind and eastward wind at the boat position.
## GetCurrent
The function GetCurrent(latitude,longitude) returns the a dictionnary with northward current and eastward current at the boat position.
Uses the secret [CopernicusMarine] username and password to login in copernicusmarine API.
## GetAisData
The function GetAisData(latitude,longitude) returns a dictionnay with boat data that are at less than 5 Nm of the boat position.
## GetUserInput
The function GetUserInput() returns the values of the user editable fields boat_key, boat_name, skipper_name, heading, wind_angle, follow_wind.
## SimulateMovement
The funtion SimulateMovement(time, boat_data, AIS_data) simulates the movement of the boat and AIS boat until the time given, with the data in boat_data and AIS_data. The boat is simulated in a very simple way: if the wind angle is smaller than +/-50°C, it stops. If the wind angle is larger, it sails with a speed of half the wind speed. True heading is used if follow_wind is false or wind_angle is used to calculate the heading if  follow_wind is true. The current speed is then added to the boat speed. Is sails in one straight step from last_update_time or last AIS update time to the time requested. The new position and time are updated in boat_data and AIS_data.
## CheckColision 
The function CheckColision(boat_data,AIS_data) verify the colision of the current boat and the closest boat in AIS_data. The triangles of both boats are calculated with function DrawBoatTriangle then it is verified that both triangles have no interference. If there is a colision, return the AIS data of the boat collided, return an empty array otherwise.
## CheckAground
The function CheckAground(latitude,longitude) check if the boat is aground using the library roaring_landmask.




