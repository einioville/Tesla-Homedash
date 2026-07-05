'''Charging-session detection + charging-loss analysis: derive charging sessions
from stored telemetry on demand and quantify where the wall energy went.

Like trip detection, sessions are not tracked live — ChargingLoader reads the
DetailedChargeState history out of InfluxDB over a window and segments it into
charging sessions. Each ChargingSession then joins the vehicle's own telemetry
(ACChargingEnergyIn, EnergyRemaining) with the myenergi charger energy logged by
MyEnergiService to compute the loss breakdown:

    charger_kwh  --(cable/metering loss)-->  ac_in_kwh  --(onboard-charger
    AC->DC conversion loss)-->  battery_kwh

All InfluxDB access goes through InfluxDBHandler (tesla_data + myenergi_data
measurements). Sessions with no matching charger energy (a car charged away from
this Zappi, or DC-fast-charged) are excluded — there is nothing to compare.
'''
