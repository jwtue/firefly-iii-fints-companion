<?php

declare(strict_types=1);

namespace App\Support;

/** One-shot flash messages carried across a redirect in the session. */
final class Flash
{
    /**
     * @param string $message a translation key; translated at render time
     * @param array<string, string|int> $params substitution parameters for the key
     */
    public static function add(string $type, string $message, array $params = []): void
    {
        $_SESSION['flash'][] = ['type' => $type, 'message' => $message, 'params' => $params];
    }

    /** @return array<int, array{type:string, message:string, params:array<string, string|int>}> */
    public static function pull(): array
    {
        $messages = $_SESSION['flash'] ?? [];
        unset($_SESSION['flash']);

        return $messages;
    }
}
