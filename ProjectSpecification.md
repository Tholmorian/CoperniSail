# Scope
This document describes the structure, functions and working process of the CoperniSail app.
# App description
The CoperniSail app is a game that let you sail a sailing dinghy from France to England. The aim is to reach an English port as fast as possible without being crushed by one of the big boats travelling in the channel. The app works in real time. It gather the real wind and current from the copernicusmarine API. It retreive the real boats positions from AIS data on the web. The user sees its boat and the other boats on a chart. It can configure the boat to follow a constant heading or a constant wind angle.
# Hosting
The database is hosted in my google cloud account. It contains boat positions and heading.
The code is ran on Streamlit could platform.
# Connections
The current and wind data are retreived from copernicusmarine API with my username and password.
The AIS boat positions are retreived from 
# General app process
When the app is loaded, the boat key field is empty. If a valid key is typed, the boat data are loaded in the database. If the key does not exist in the database it is created. If the key is not valid, the user is informed. To get a valid key the user shall ask it to the Webmaster. A key validity is tested by a function described below.
When a boat is loaded, the app updates every 60s.
The boat position is 
