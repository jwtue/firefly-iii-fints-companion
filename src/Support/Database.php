<?php

declare(strict_types=1);

namespace App\Support;

use PDO;

/**
 * Thin wrapper around a PDO SQLite connection plus a tiny, idempotent migration runner.
 *
 * The normalized model (logins, accounts) lives here rather than in the importer's flat JSON files,
 * because credentials and the TAN persistence string are shared across accounts of the same login.
 * The flat importer configs are rendered from this store on demand (see {@see \App\Config\ConfigRenderer}).
 */
final class Database
{
    private PDO $pdo;

    public function __construct(string $path)
    {
        if ($path !== ':memory:') {
            $dir = dirname($path);
            if (!is_dir($dir)) {
                mkdir($dir, 0o770, true);
            }
        }

        $this->pdo = new PDO('sqlite:' . $path, null, null, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]);
        $this->pdo->exec('PRAGMA journal_mode = WAL');
        $this->pdo->exec('PRAGMA foreign_keys = ON');
        $this->migrate();
    }

    public function pdo(): PDO
    {
        return $this->pdo;
    }

    private function migrate(): void
    {
        $this->pdo->exec(<<<'SQL'
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS logins (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                name                  TEXT NOT NULL,
                bank_url              TEXT NOT NULL DEFAULT '',
                bank_code             TEXT NOT NULL DEFAULT '',
                bank_username         TEXT NOT NULL DEFAULT '',
                bank_password         TEXT NOT NULL DEFAULT '',
                bank_2fa              TEXT NOT NULL DEFAULT '',
                bank_2fa_device       TEXT NOT NULL DEFAULT '',
                fints_persistence     TEXT NOT NULL DEFAULT '',
                persistence_updated_at TEXT,
                created_at            TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS accounts (
                id                        INTEGER PRIMARY KEY AUTOINCREMENT,
                login_id                  INTEGER NOT NULL REFERENCES logins(id) ON DELETE CASCADE,
                name                      TEXT NOT NULL,
                slug                      TEXT NOT NULL UNIQUE,
                selector_type             TEXT NOT NULL DEFAULT 'iban',
                bank_account_iban         TEXT NOT NULL DEFAULT '',
                bank_account_number       TEXT NOT NULL DEFAULT '',
                firefly_account_id        TEXT NOT NULL DEFAULT '',
                date_from                 TEXT NOT NULL DEFAULT 'now - 7 days',
                date_to                   TEXT NOT NULL DEFAULT 'now',
                description_regex_match   TEXT NOT NULL DEFAULT '',
                description_regex_replace TEXT NOT NULL DEFAULT '',
                force_mt940               INTEGER NOT NULL DEFAULT 0,
                skip_transaction_review   INTEGER NOT NULL DEFAULT 1,
                schedule_cron             TEXT NOT NULL DEFAULT '',
                enabled                   INTEGER NOT NULL DEFAULT 1,
                created_at                TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at                TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS runs (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id        INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
                account_name      TEXT NOT NULL DEFAULT '',
                login_id          INTEGER,
                trigger           TEXT NOT NULL DEFAULT 'manual',
                status            TEXT NOT NULL DEFAULT 'running',
                outcome_reason    TEXT NOT NULL DEFAULT '',
                http_status       INTEGER,
                response_excerpt  TEXT NOT NULL DEFAULT '',
                num_transactions  INTEGER,
                started_at        TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at       TEXT,
                duration_ms       INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_runs_started  ON runs(started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_runs_account  ON runs(account_id);
            CREATE INDEX IF NOT EXISTS idx_accounts_login ON accounts(login_id);
        SQL);
    }
}
