<?php

declare(strict_types=1);

namespace App\Support;

use PDO;

/**
 * Replaces known secrets with a placeholder before anything is stored or sent onwards.
 *
 * The importer, running with display_errors on, can echo credentials inside an HTML stack trace, so
 * every response body kept in the run history is passed through here, as is every notification. The
 * secret set is built from the current logins (passwords, persistence strings) and the Firefly token.
 */
final class Redactor
{
    private const PLACEHOLDER = '***';

    /** @var string[] secrets ordered longest-first so overlapping values redact cleanly */
    private array $secrets;

    /** @param string[] $secrets */
    public function __construct(array $secrets)
    {
        $secrets = array_values(array_unique(array_filter(
            $secrets,
            // Ignore very short values: redacting them would blank out unrelated text.
            static fn (string $s): bool => strlen($s) >= 4
        )));
        usort($secrets, static fn (string $a, string $b): int => strlen($b) <=> strlen($a));
        $this->secrets = $secrets;
    }

    public static function fromDatabase(PDO $pdo, Settings $settings): self
    {
        $secrets = [];
        $rows = $pdo->query('SELECT bank_password, fints_persistence FROM logins')->fetchAll();
        foreach ($rows as $row) {
            $secrets[] = (string) $row['bank_password'];
            $secrets[] = (string) $row['fints_persistence'];
        }
        $secrets[] = $settings->get('firefly_token');

        return new self($secrets);
    }

    public function redact(string $text): string
    {
        if ($text === '') {
            return $text;
        }
        foreach ($this->secrets as $secret) {
            $text = str_replace($secret, self::PLACEHOLDER, $text);
        }

        return $text;
    }
}
