<?php

declare(strict_types=1);

namespace App\Support;

use PDO;

/**
 * Global, single-instance settings: the Firefly connection (one instance), the importer URL and the
 * Telegram credentials. Stored in the settings table, each key overridable by an environment variable
 * so the container can be configured either way. Per-login and per-account data live in their own
 * tables, not here.
 */
final class Settings
{
    /** setting key => environment variable that overrides it */
    private const ENV = [
        'firefly_url'            => 'SIDECAR_FIREFLY_URL',
        'firefly_token'          => 'SIDECAR_FIREFLY_TOKEN',
        'importer_url'           => 'SIDECAR_IMPORTER_URL',
        'importer_supports_json' => 'SIDECAR_IMPORTER_SUPPORTS_JSON',
        'telegram_bot_token'     => 'SIDECAR_TELEGRAM_BOT_TOKEN',
        'telegram_chat_id'       => 'SIDECAR_TELEGRAM_CHAT_ID',
        'notify_on_failure'      => 'SIDECAR_NOTIFY_ON_FAILURE',
        'notify_on_tan'          => 'SIDECAR_NOTIFY_ON_TAN',
        'notify_on_success'      => 'SIDECAR_NOTIFY_ON_SUCCESS',
        'notify_on_missing'      => 'SIDECAR_NOTIFY_ON_MISSING',
    ];

    public function __construct(private readonly PDO $pdo)
    {
    }

    public function get(string $key, string $default = ''): string
    {
        $env = self::ENV[$key] ?? null;
        if ($env !== null) {
            $value = getenv($env);
            if ($value !== false && $value !== '') {
                return $value;
            }
        }

        $stmt = $this->pdo->prepare('SELECT value FROM settings WHERE key = ?');
        $stmt->execute([$key]);
        $value = $stmt->fetchColumn();

        return $value === false || $value === null ? $default : (string) $value;
    }

    public function bool(string $key, bool $default = false): bool
    {
        $value = strtolower(trim($this->get($key, $default ? '1' : '0')));

        return in_array($value, ['1', 'true', 'yes', 'on'], true);
    }

    public function set(string $key, string $value): void
    {
        // An environment override wins on read, so never persist over one silently — but still store it,
        // so removing the variable later falls back to the configured value.
        $stmt = $this->pdo->prepare(
            'INSERT INTO settings (key, value) VALUES (?, ?)
             ON CONFLICT(key) DO UPDATE SET value = excluded.value'
        );
        $stmt->execute([$key, $value]);
    }

    /** True when a setting is fixed by the environment and therefore read-only in the UI. */
    public function isFromEnv(string $key): bool
    {
        $env = self::ENV[$key] ?? null;
        if ($env === null) {
            return false;
        }
        $value = getenv($env);

        return $value !== false && $value !== '';
    }
}
