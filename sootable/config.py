"""Every placeholder value from the spec lives here so it is easy to change."""

DEFAULT_LIMIT_K = 2.45          # CMVR limit, 65 HSU (m^-1)
DEFAULT_PATH_LEN_M = 0.10       # optical path length L
MIN_I0 = 200                    # below this the reference is unusable
NOISE_TOLERANCE = 5             # counts i may exceed i0 and still count as k = 0
WATCH_FRACTION = 0.80           # WATCH starts at 80% of the limit
RISE_FACTOR = 1.5               # RISE when smoothed >= 1.5 x baseline
HYSTERESIS = 0.95               # an alert level only resets once smoothed is below 95% of its threshold
RISE_RELEASE_FACTOR = 1.25     # a fired RISE only resets once smoothed falls below this x baseline
RISE_STEPS_NEEDED = 3          # ... and rose on this many of the last 5 days
SMOOTH_DAYS = 7                 # daily values averaged for the trend
SMOOTH_WINDOW_DAYS = 14         # only days inside this window count
SMOOTH_MIN_VALUES = 3           # fewer daily values than this = no trend yet
BASELINE_DAYS = 14              # daily values that make up the baseline
ALERT_COOLDOWN_S = 7 * 86400    # one notification per alert type per week
CLEAN_REMINDER_READINGS = 30    # remind the owner to clean the chamber
MAX_PAST_S = 400 * 86400        # taken_at older than this is invalid
RETENTION_DAYS = 1000           # readings older than this are deleted (about 1 reading a day)
FORECAST_MIN_POINTS = 14        # daily values needed in the last 60 days to estimate a trend
FORECAST_MIN_SLOPE = 0.0015     # m^-1 per day (about 0.05 a month); flatter than this is "steady"
FORECAST_MAX_DAYS = 365         # do not show a date further out than a year
MAX_ALERTS = 200               # the alerts log keeps only the newest ones
