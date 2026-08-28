'''Runtime configuration (the Options view): serve, validate, persist and apply
the settings in config.json that are safe to change without editing the file.

ConfigService publishes a schema of editable settings over the CONFIG_* protocol
codes, so config.json's structural parts (the `tesla data` table the frontend
registry mirrors) stay out of reach. Because every service snapshots its config at
construction, applying a change means calling that service's apply_config() hook —
settings with no such path are marked restart-tier and picked up on the next start.
'''
