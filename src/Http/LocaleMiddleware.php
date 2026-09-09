<?php

declare(strict_types=1);

namespace App\Http;

use App\Support\Translator;
use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;
use Psr\Http\Server\MiddlewareInterface;
use Psr\Http\Server\RequestHandlerInterface;

/** Resolves the UI language per request (cookie > Accept-Language > default) and sets it on the translator. */
final class LocaleMiddleware implements MiddlewareInterface
{
    public function __construct(private readonly Translator $translator)
    {
    }

    public function process(ServerRequestInterface $request, RequestHandlerInterface $handler): ResponseInterface
    {
        $cookie = $request->getCookieParams()['lang'] ?? null;
        $this->translator->setLocale(
            $this->translator->resolve(is_string($cookie) ? $cookie : null, $request->getHeaderLine('Accept-Language'))
        );

        return $handler->handle($request);
    }
}
