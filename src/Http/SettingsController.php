<?php

declare(strict_types=1);

namespace App\Http;

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

    public function __construct(
        private readonly Twig $view,
        private readonly Settings $settings,
    ) {
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
        Flash::add('success', 'flash.settings_saved');

        return $response->withHeader('Location', '/settings')->withStatus(302);
    }
}
