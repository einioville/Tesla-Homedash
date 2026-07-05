'''MyEnergi (Zappi) charger integration: live streaming + InfluxDB logging.

MyEnergiService polls the myenergi cloud (via the pymyenergi library — director
discovery + digest auth with the hub serial as username and an API key as password),
broadcasts the Zappi's live state to every frontend as a CHARGER_STREAM frame, and
logs the session-energy accumulator to the "myenergi_data" InfluxDB measurement so the
charging-loss analysis (see charging_service) can join it to the vehicle telemetry.

The service self-disables when credentials are absent (a deployment without a Zappi
still starts) — the credentials live in .env (MYENERGI_HUB_SERIAL / MYENERGI_API_KEY),
the non-secret tunables in config.json's "myenergi" block.
'''
