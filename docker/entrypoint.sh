#!/bin/sh
set -e

# Optionally run the scheduler in the background so a single container can serve the UI and run
# scheduled imports. It respawns if it exits. Disabled by default; enable with SIDECAR_RUN_SCHEDULER=true.
# To run a dedicated scheduler-only container instead, override the command with: php bin/scheduler.php
if [ "${SIDECAR_RUN_SCHEDULER:-false}" = "true" ]; then
    (
        while true; do
            php /app/bin/scheduler.php || echo "[entrypoint] scheduler exited ($?), restarting in 5s"
            sleep 5
        done
    ) &
fi

exec frankenphp run --config /etc/caddy/Caddyfile
