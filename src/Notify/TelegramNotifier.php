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
        // ImporterTransport::get never throws; a failed delivery is silently dropped by contract.
        $this->http->get($this->buildUrl(trim($title . "\n" . $message)));
    }

    public function test(): array
    {
        if (!$this->isConfigured()) {
            return ['ok' => false, 'detail' => 'not configured'];
        }
        $response = $this->http->get($this->buildUrl('✅ FinTS Companion — test message'));
        $data = json_decode((string) $response['body'], true);
        if ((int) $response['status'] === 200 && is_array($data) && ($data['ok'] ?? false) === true) {
            return ['ok' => true, 'detail' => ''];
        }
        // Telegram returns {"ok":false,"description":"..."} on error; fall back to the status code.
        $detail = is_array($data) && isset($data['description'])
            ? (string) $data['description']
            : ('HTTP ' . $response['status']);

        return ['ok' => false, 'detail' => $detail];
    }

    private function buildUrl(string $text): string
    {
        return 'https://api.telegram.org/bot' . rawurlencode($this->botToken) . '/sendMessage'
            . '?chat_id=' . rawurlencode($this->chatId)
            . '&disable_web_page_preview=true'
            . '&text=' . rawurlencode($text);
    }
}
