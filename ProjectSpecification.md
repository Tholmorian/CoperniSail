# Scope
This document describes the structure, functions and working process of the CoperniSail app.
# App description
The CoperniSail app is a game that let you sail a sailing dinghy from France to England. The aim is to reach an English port as fast as possible without being crushed by one of the big boats travelling in the channel. The app works in real time. It gather the real wind and current from the copernicusmarine API. It retreive the real boats positions from AIS data on the web. The user sees its boat and the other boats on a chart. It can configure the boat to follow a constant heading or a constant wind angle.
# Hosting
The database is hosted in my google cloud account, in a Firestore database. It contains boat positions and heading.
The code is ran on Streamlit could platform at the address https://copernisail.streamlit.app/ .
# Connections
The current and wind data are retreived from copernicusmarine API with my username and password.
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
***

# Functions descriptions
## CoperniSail
The CoperniSail script file is the entry point of the app called by Streamlit when a user connect.
***
# 
