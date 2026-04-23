'''
Shared binary protocol constants used by the TCP server and the media layer.
Keeping these in a single module prevents silent divergence between the
backend's outgoing byte values and the ones the frontend expects.  All
values are single bytes unless noted otherwise.  See CLAUDE.md
"Binary Protocol Reference" for the authoritative specification.
'''

# Frontend-to-backend and backend-to-frontend Tesla-data framing
MSG_JSON = 0x01
MSG_LIST = 0x02
MSG_TERMINATE = 0x03
MSG_STREAM = 0x04

# Media stream and control bytes
MEDIA_STREAM_IMAGE = 0x14
MEDIA_STREAM_NAME = 0x15
MEDIA_STREAM_PROGRESS = 0x16
MEDIA_STREAM_DURATION = 0x17
MEDIA_SKIP = 0x18
MEDIA_SKIP_BACKWARD = 0x19
MEDIA_PAUSE_PLAY = 0x1A
MEDIA_IS_PLAYING = 0x1B
MEDIA_SET_PROGRESS = 0x1C
MEDIA_STREAM_ARTISTS = 0x1D
MEDIA_STREAM_TYPE = 0x1E

# Media-type byte values carried inside MEDIA_STREAM_TYPE payloads
MEDIA_TYPE_RADIO = 0x01
MEDIA_TYPE_SPOTIFY = 0x02

# Weather forecast frame and sub-field IDs
WEATHER_FORECAST = 0x30
FORECAST_TEMPERATURE = 0x31
FORECAST_WIND_SPEED = 0x32
FORECAST_PRECIPITATION = 0x33
FORECAST_TOTAL_CLOUD_COVER = 0x34
FORECAST_TIME = 0x35

# Tesla command bytes (frontend -> backend)
TESLA_SWITCH_CLIMATE_STATE = 0x60
TESLA_MINUS_TARGET_TEMP = 0x61
TESLA_PLUS_TARGET_TEMP = 0x62

# Maximum accepted size of a single incoming message (defensive cap)
MAX_MSG_SIZE = 1024 * 1024  # 1 MB
