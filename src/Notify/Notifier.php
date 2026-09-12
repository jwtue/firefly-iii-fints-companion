<?php

declare(strict_types=1);

namespace App\Notify;

/**
 * A notification channel. Messages are already redacted by the caller. Implementations must not
 * throw — a failing notification must never fail the run it is reporting on.
 */
interface Notifier
{
    public function send(string $title, string $message): void;

    /** Whether this channel is configured and will actually deliver. */
    public function isConfigured(): bool;

    /**
     * Send a test message and report whether delivery actually succeeded.
     *
     * @return array{ok: bool, detail: string}
     */
    public function test(): array;
}
