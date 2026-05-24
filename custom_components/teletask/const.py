"""Constants for the Teletask integration."""

DOMAIN = "teletask"

CONF_CENTRAL_ID  = "central_id"
CONF_HOST        = "host"
CONF_PORT        = "port"
CONF_CONFIG_JSON = "config_json"

DEFAULT_PORT = 55957

# Dispatcher signal format
SIGNAL_STATE_UPDATED = "teletask_{central_id}_{function}_{number}_state"
