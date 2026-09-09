# FrankenPHP: a single production-grade process serving the app — not the PHP dev server.
FROM dunglas/frankenphp:1-php8.4

# unzip/git let Composer extract packages; pdo_sqlite for the state database, zip for extraction.
RUN apt-get update \
    && apt-get install -y --no-install-recommends unzip git \
    && rm -rf /var/lib/apt/lists/* \
    && install-php-extensions pdo_sqlite zip

WORKDIR /app

# Install dependencies first for better layer caching.
COPY composer.json composer.lock ./
RUN curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer \
    && composer install --no-dev --no-interaction --no-progress --optimize-autoloader --no-scripts \
    && rm -f /usr/local/bin/composer

COPY . .

# Serve the public/ directory (see Caddyfile).
COPY Caddyfile /etc/caddy/Caddyfile

# Normalize line endings (in case of a Windows checkout) and make the entrypoint executable.
RUN sed -i 's/\r$//' /app/docker/entrypoint.sh && chmod +x /app/docker/entrypoint.sh

# The state database and the rendered importer configs live under /data (mount a volume there).
ENV SIDECAR_DATABASE_PATH=/data/sidecar/sidecar.sqlite \
    SIDECAR_CONFIG_DIR=/data/configurations \
    SIDECAR_LOCK_FILE=/data/sidecar/run.lock

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

# Default command serves the UI and, if SIDECAR_RUN_SCHEDULER=true, runs the scheduler in the same
# container (all-in-one). Override with `php bin/scheduler.php` for a dedicated scheduler container.
CMD ["/app/docker/entrypoint.sh"]
