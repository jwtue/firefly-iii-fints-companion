<?php

declare(strict_types=1);

namespace App\Notify;

/** Used when no notification channel is configured. Does nothing. */
final class NullNotifier implements Notifier
{
    public function isConfigured(): bool
    {
        return false;
    }

    public function send(string $title, string $message): void
    {
    }

    public function test(): array
    {
        return ['ok' => false, 'detail' => 'not configured'];
    }
}
