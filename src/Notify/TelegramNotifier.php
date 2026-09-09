<?php

declare(strict_types=1);

namespace App\Notify;

use App\Importer\ImporterTransport;

/**
 * Sends notifications to a Telegram chat via the Bot API. Reuses the {@see ImporterTransport}
 * abstraction for HTTP so it stays testable and never throws on a delivery failure.
 */
final class TelegramNotifier implements Notifier
{
    public function __construct(
        private readonly ImporterTransport $http,
        private readonly string $botToken,
        private readonly string $chatId,
    ) {
    }

    public function isConfigured(): bool
    {
        return $this->botToken !== '' && $this->chatId !== '';
    }

    public function send(string $title, string $message): void
    {
        if (!$this->isConfigured()) {
            return;
        }
        $text = trim($title . "\n" . $message);
        $url = 'https://api.telegram.org/bot' . rawurlencode($this->botToken) . '/sendMessage'
            . '?chat_id=' . rawurlencode($this->chatId)
            . '&disable_web_page_preview=true'
            . '&text=' . rawurlencode($text);

        // ImporterTransport::get never throws; a failed delivery is silently dropped by contract.
        $this->http->get($url);
    }
}
