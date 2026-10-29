# Scope
This document describes the structure, functions and working process of the CoperniSail app.
# App description
The CoperniSail app is a game that let you sail a dinghy from France to England. The aim is to reach an English port as fast as possible without being crushed by one of the big boats travelling in the channel. The app works in real time. It gather the real wind and current from the copernicusmarine API. It retreive the real boats positions from AIS data on the web. The user sees its boat and the other boats on a chart. It can choose the desired heading the tack, the minimum and maximum wind angle.
# Hosting
The database is hosted in my google cloud account, in a Firestore database. It contains boat positions and heading. The Firestore collection name is 'sim_state' and the document name is 'current'.
The code is ran on Streamlit could platform at the address https://copernisail.streamlit.app/ .
# Connections
The current data are retreived from copernicusmarine API with my username and password.
The wind data are retrieved from api.open-meteo.com without account.
The AIS boat positions are retreived from ais.openwaters.io website without account.
The waypoints are in a json file waypoint.json

# General app process
When the app is loaded, the boat key field is empty. If a valid key is typed, the boat data are loaded in the database. If the key does not exist in the database it is created. If the key is not valid, the user is informed. To get a valid key the user shall ask it to the Webmaster. When a boat is loaded, the app updates every 60s.
The updating process is done every 60s for the user's boat then its user interface is updated. Then the updating process is also done for the other boats that have not been updated from more than 5min. The wind, current and surrounding boats AIS positions are loaded from internet websites. The boat movement is simulated. The simulation check that there is no collision with another boat or with the ground. The boats are created at the start position. They are returned to the start position if they collide, get aground or arrive. If the boat arrives, its best travel time can be updated. The user interface has a large map showing the boat and the surrounding AIS retreived boats. It has controls for heading and tack, and indications of GPS heading and speed. A link to windy.com prevision is provided and the last important event.
A button can show the hall of fame of the best 20 times to arrival, and the user position in the hall of fame.
# Database description
The database data contains all the following fields for each entry:
- boat_key: Secret ID of the boat, known by the webmaster and the owner.
- boat_name: Name of the boat
- skipper_name: Name of the skipper
- last_update_time: Time of last update of boat data in UTC iso format
- latitude: latitude of the boat in decimal degree at the last update time
- longitude: longitude of the boat in decimal degree at the last update time
- heading: heading of the boat, not heading of course over ground.
- heading_target: heading desired by the skipper, but constrained by tack, min_wind_angle and max_wind_angle
- true_heading heading over ground
- tack: current tack of the boat, either port or starboard or stopped.
- min_wind_angle: the minimum true wind angle of the boat.
- max_wind_angle: the maximum wind angle of the boat.
- speed: speed in knots relative to ground at the time of last update
- best_time_to_arrival: duration in second of the best race time of the boat
- start_time: Time when starting race in UTC iso format
- meteo_update_time: Time when meteo of the boat has last been updated in UTC iso format
- wind_speed: Wind speed at boat position in m/s
- wind_direction: Wind direction at boat position in degree
- current_speed: Current speed at boat position in m/s
- current_direction: Current direction at boat position in degree
- information: a string to retain the last important event for the user interface
The database login data are stored in the secrets file of the Streamlit cloud. 

# Functions descriptions

## CoperniSail
The CoperniSail script file is the entry point of the app called by Streamlit when a user connect. It loops every 60s. In each loop, it loops through all boats in the database, starting by the boat which has the boat key indicated in the boat key field. It follows with the boat that has the oldest update time and repeat until every update time is more recent than 5min. The loop content is described hereunder:

The updating process consists in these steps: Load the boat data in the database. Update the last update time in the database so that other users do not try to update the boat data. If it is my boat, get boat controls in the user interface. Load the current at the boat position. Load the wind at the boat position. Load the surrouning boat AIS data. Simulate the boat movement and the surrounding boats movements to check for collisions. Check if the boat is arrived at the race goal. Update the boat data in the database. If it is my boat, update the user interface.

- If the boat do not exist and the key is valid as tested by function ValidKey, create a new boat with function MakeBoat.
- Update in database last_update_time for the boat to prevent update by another user
- If meteo is older than 10min, update meteo data with function GetWind and function GetCurrent. Keep values to update all boat data in database at once.
- Load AIS data with function GetAisData.
- If the simulated boat is my boat, get controls from user interface with function GetUserInput.
- Simulate the boats displacement from last_update_time to now to detect colisions by looping by 10s step with function SimulateMovement. If position is older than 15min, do not simulate, update last_update_time only. Keep new boat position.
- If a colision has been detected, reset boat position.
- If the boat is aground, reset boat position.
- If the boat is in the start zone, update start_time.
- If the boat is in the arrival zone, update best_time_to_arrival if applicable.
- Save boat data in the database.
- If the simulated boat is my boat, update map.
## GenerateKey
The function GenerateKey() returns a random key with only capital letters and numbers. The key generates 8 random characters then encode them with the secret [KeyTester] secret_key. The random and encoded charactes are interlaced.
## ValidKey
The function ValidKey(key) returns true if the key is valid.
## GetMyBoat
the function GetMyBoat(key) Query the data of the boat with key in the Firestore database. Use the secrets in [Firestore] to login.
## GetLastBoat
The function GetLastBoat() Query the data of the boat with the oldest last_update_time in the Firestore database. Use the secrets under [Firestore] to login. It returns a dictionnary with the boat data.
## Makeboat
The function Makeboat(key) creates a boat in the database with default values.
## GetWind
The function GetWind(latitude,longitude) returns the a dictionnary with northward wind and eastward wind at the boat position. The values are in knots.
## GetCurrent
The function GetCurrent(latitude,longitude) returns the a dictionnary with northward current and eastward current at the boat position.
Uses the secret [CopernicusMarine] username and password to login in copernicusmarine API. The values are in knots.
## GetAisData
The function GetAisData(latitude,longitude) returns a dictionnay with boat data that are at less than 5 Nm of the boat position. The data are 'Name':string,'Length':value in m,'Speed':value in knots,'Heading':value in degree,'UpdateTime':'string with time in ISO format. 
## GetUserInput
The function GetUserInput() returns the values of the user editable fields boat_key, boat_name, skipper_name, heading_target, tack.
## SimulateMovement
The funtion SimulateMovement(time, boat_data, AIS_data,waypoints) simulates the movement of the boat and AIS boat until the time given, with the data in boat_data and AIS_data. The boat is simulated in a very simple way: The boat is on the closest heading from heading_target but with the constrain that it is on the desired tack and wind angle is higher than min_wind_angle and smaller than max_wind_angles. If the tack is stopped. The boat is at anchorage. The boat navigates with a speed of half the wind speed with a maximum of 5 knots. The current speed is then added to the boat speed. Is sails in one straight step from last_update_time or last AIS update time to the time requested. The new position and time are updated in boat_data and AIS_data. The CheckColision, CheckAground, and CheckWaypoint are done at each simulation step.
## CheckColision 
The function CheckColision(boat_data,AIS_data) verify the colision of the current boat and the closest boat in AIS_data. The triangles of both boats are calculated with function DrawBoatTriangle then it is verified that both triangles have no interference. If there is a colision, return the AIS data of the boat collided, return an empty array otherwise.
## CheckAground
The function CheckAground(latitude,longitude) check if the boat is aground using the library roaring_landmask.
## CheckWaypoint
The function CheckWaypoint(latitude,longitude,waypoints) check if the boat is in a passage zone. It returns 0 if the boat is not in a passage zone or the waypoint 'number' if in a waypoint. Number 1 is the start zone and number 100 is the arrival zone. .
## GetWaypoint
The function GetWaypoint() returns the waypoints as found in a json file 'waypoints.json'. It contains a list of waypoints with fields 'number','latitude','longitude','radius'. There is at least a number 1 for dearture and a number 100 for arrival.
It outout a dictionnary with with 'number','latitude','longitude','radius'. Each contain a list of values.
## DrawInterface
The function DrawInterface(boat_data, AIS_data) draws the user interface. It uses folium.Map to draw a map, centered on user boat, with triangles drawn for my boat and the boats of AIS. A tooltip with boat name, length and speed is given when the cursor is placed on an AIS boat. A 5 miles circle with a line every 10 degree is drawn around my boat.
folium.TileLayer(tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      attr="Tiles &copy; Esri",
      name="Esri Satellite",
  )
Beside the map are drawn a boat key and a heading editable fields and a tack selector (port or starboard). Other fields with the true heading and speed and the boat information are also drawn.
## DrawTriangle
The function DrawTriangle(latitude,longitude,length,heading) returns the coordinates of a triangle centered in boat position, with boat length and a width of 1/3 of boat length. The output is a dictionnary with keys latitude and longitude. Both are a list of 3 values.
## 

