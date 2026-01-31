# Tesla-Homedash
Tesla-Homedash is a smart home dashboard, which integrates Tesla vehicles, radio player, Spotify, weather forecast and eventually many other services into a single app.

This is my side project I will be working on besides school

## Features
- Telemetry from Tesla vehicles
	- Store and display real-time telemetry data from your vehicle. Provided by [Teslemetry](https://teslemetry.com/)
		- I am planning to implement my own telemetry server later on
- Execute commands on Tesla vehicles
	- Turn on and adjust AC settings on your vehicle. Provided by [Teslemetry](https://teslemetry.com/)
- Weather forecast
	- Hourly forecast. Provided by [Open data - Finnish Meteorological Institute](https://en.ilmatieteenlaitos.fi/open-data)
		- Temperature
		- Wind speed
		- Precipitation
		- Cloud cover
- Spotify
	- Control Spotify playback from the UI
	- With [Spotifyd/spotifyd: A spotify daemon](https://github.com/Spotifyd/spotifyd), Linux device running the server can automatically switch between the radio and Spotify playback
- Web radio player
## UI
### Home Screen
- Map the display wherever your Tesla is located
- Live and historical driving statistics
- Media player 
	- Spotify
	- Web radio
- Hourly weather forecast
- Climate controller
![Main Screen](https://github.com/einioville/Tesla-Homedash/blob/main/docs/images/Screenshot%202026-01-29%20154107.png?raw=true)
