"""Constants for the Teletask integration."""

DOMAIN = "teletask"

CONF_CENTRAL_ID  = "central_id"
CONF_HOST        = "host"
CONF_PORT        = "port"
CONF_CONFIG_JSON  = "config_json"
CONF_DEBUG_LOG    = "debug_log"

DEFAULT_PORT = 55957

# Dispatcher signal format
SIGNAL_STATE_UPDATED = "teletask_{central_id}_{function}_{number}_state"

# HA bus event fired when the TeleTask central reports a state change
# for entity types that have no writable HA state (scenes, momentary buttons).
# Payload: {"function": str, "number": int, "description": str, "state": str}
TELETASK_EVENT = "teletask_event"
