'''Trip detection (issue #5): derive trips from stored telemetry on demand.

Trips are not tracked live — TripLoader reads the Gear / ShiftState history out of
InfluxDB over a window and segments it into trips, and each Trip computes its summary
from the same stored telemetry. All InfluxDB access goes through InfluxDBHandler.
'''
