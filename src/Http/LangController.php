<?php

declare(strict_types=1);

namespace App\Http;

use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;

/** Sets the language cookie and returns to the page the user came from. */
final class LangController
{
    public function switch(ServerRequestInterface $request, ResponseInterface $response, array $args): ResponseInterface
    {
        $locale = ($args['locale'] ?? 'en') === 'de' ? 'de' : 'en';
        // Return to the referring path only (never a full URL) to avoid an open redirect.
        $referer = $request->getHeaderLine('Referer');
        $path = $referer !== '' ? (parse_url($referer, PHP_URL_PATH) ?: '/') : '/';

        return $response
            ->withHeader('Set-Cookie', 'lang=' . $locale . '; Path=/; Max-Age=31536000; SameSite=Lax')
            ->withHeader('Location', $path)
            ->withStatus(302);
    }
}
