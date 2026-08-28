#!/usr/bin/with-contenv bashio
# Mesh Sentinel reads /data/options.json itself; bashio is used only for logging
# and for the one setting the Supervisor cannot express in the options schema.
set -e

LOG_LEVEL="$(bashio::config 'log_level' 'info')"
export MESH_SENTINEL_LOG_LEVEL="$(echo "${LOG_LEVEL}" | tr '[:lower:]' '[:upper:]')"
export MESH_SENTINEL_DB_PATH="/data/mesh_sentinel.db"
export MESH_SENTINEL_PORT="8099"

bashio::log.info "Starting Mesh Sentinel 0.1.0 (log level ${LOG_LEVEL})"
if bashio::services.available "mqtt"; then
  bashio::log.info "An MQTT service is registered with the Supervisor; it will be used unless you set a broker in the options."
else
  bashio::log.warning "No MQTT service registered. Set mqtt_host in the app options, or install the Mosquitto app."
fi

cd /app
exec python3 -m mesh_sentinel
