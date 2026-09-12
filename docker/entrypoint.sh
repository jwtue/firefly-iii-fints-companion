#!/bin/sh
set -e

# The scheduler runs in the background by default, so a single container serves the UI and runs the
# schedules configured there. It is a dry-run switch: set SIDECAR_RUN_SCHEDULER=false to disable it
# (nothing runs automatically, only manual "Run now"). Any value other than "false" keeps it on.
# It respawns if it exits. To run a dedicated scheduler-only container instead, override the command
# with: php bin/scheduler.php
RUN_SCHEDULER=$(printf '%s' "${SIDECAR_RUN_SCHEDULER:-true}" | tr '[:upper:]' '[:lower:]')
if [ "$RUN_SCHEDULER" != "false" ]; then
    (
        while true; do
            php /app/bin/scheduler.php || echo "[entrypoint] scheduler exited ($?), restarting in 5s"
            sleep 5
        done
    ) &
fi

exec frankenphp run --config /etc/caddy/Caddyfile
