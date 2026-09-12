<?php

declare(strict_types=1);

namespace App\Http;

use App\Importer\ImporterTransport;
use App\Notify\TelegramNotifier;
use App\Support\Flash;
use App\Support\Settings;
use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;
use Slim\Views\Twig;

/**
 * The global, single-instance settings: the Firefly connection, the importer URL and the Telegram
 * credentials. Secret fields (the Firefly token, the Telegram bot token) are never sent to the
 * browser; leaving them blank on save keeps the stored value. Values fixed by an environment
 * variable are shown read-only.
 */
final class SettingsController
{
    private const PLAIN = ['firefly_url', 'importer_url', 'telegram_chat_id'];
    private const SECRET = ['firefly_token', 'telegram_bot_token'];
    /** Notification category toggles => default when never configured. */
    private const NOTIFY = [
        'notify_on_failure' => true,
        'notify_on_tan' => true,
        'notify_on_success' => false,
        'notify_on_missing' => true,
    ];

    public function __construct(
        private readonly Twig $view,
        private readonly Settings $settings,
        private readonly ImporterTransport $transport,
    ) {
    }

    /**
     * Send a Telegram test message using the values in the form (falling back to the stored ones) and
     * report whether it actually arrived. Does not save the settings.
     */
    public function testTelegram(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        $body = (array) $request->getParsedBody();
        $token = trim((string) ($body['telegram_bot_token'] ?? '')) ?: $this->settings->get('telegram_bot_token');
        $chat = trim((string) ($body['telegram_chat_id'] ?? '')) ?: $this->settings->get('telegram_chat_id');

        $result = (new TelegramNotifier($this->transport, $token, $chat))->test();
        if ($result['ok']) {
            Flash::add('success', 'flash.telegram_test_ok');
        } else {
            Flash::add('error', 'flash.telegram_test_fail', ['detail' => $result['detail']]);
        }

        return $response->withHeader('Location', '/settings')->withStatus(302);
    }

    public function edit(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        $values = [];
        $fromEnv = [];
        foreach ([...self::PLAIN, ...self::SECRET] as $key) {
            $values[$key] = in_array($key, self::SECRET, true) ? '' : $this->settings->get($key);
            $fromEnv[$key] = $this->settings->isFromEnv($key);
            // Show whether a secret is set, without revealing it.
            if (in_array($key, self::SECRET, true)) {
                $values[$key . '_set'] = $this->settings->get($key) !== '';
            }
        }

        foreach (self::NOTIFY as $key => $default) {
            $values[$key] = $this->settings->bool($key, $default);
            $fromEnv[$key] = $this->settings->isFromEnv($key);
        }

        return $this->view->render($response, 'settings.twig', ['values' => $values, 'from_env' => $fromEnv]);
    }

    public function update(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        $body = (array) $request->getParsedBody();
        foreach (self::PLAIN as $key) {
            if (!$this->settings->isFromEnv($key)) {
                $this->settings->set($key, trim((string) ($body[$key] ?? '')));
            }
        }
        foreach (self::SECRET as $key) {
            if ($this->settings->isFromEnv($key)) {
                continue;
            }
            $value = trim((string) ($body[$key] ?? ''));
            // An empty secret field keeps the stored value.
            if ($value !== '') {
                $this->settings->set($key, $value);
            }
        }
        foreach (array_keys(self::NOTIFY) as $key) {
            if (!$this->settings->isFromEnv($key)) {
                $this->settings->set($key, isset($body[$key]) ? '1' : '0');
            }
        }
        Flash::add('success', 'flash.settings_saved');

        return $response->withHeader('Location', '/settings')->withStatus(302);
    }
}
