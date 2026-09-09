<?php

declare(strict_types=1);

namespace App\Http;

use App\Support\Csrf;
use App\Support\Flash;
use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;
use Psr\Http\Server\MiddlewareInterface;
use Psr\Http\Server\RequestHandlerInterface;
use Slim\Psr7\Response;

/** Rejects state-changing requests (POST) whose CSRF token does not match the session. */
final class CsrfMiddleware implements MiddlewareInterface
{
    public function process(ServerRequestInterface $request, RequestHandlerInterface $handler): ResponseInterface
    {
        if (in_array($request->getMethod(), ['POST', 'PUT', 'PATCH', 'DELETE'], true)) {
            $body = (array) $request->getParsedBody();
            if (!Csrf::check($body['_csrf'] ?? null)) {
                Flash::add('error', 'Your session expired. Please try again.');
                $response = new Response();

                return $response->withHeader('Location', $request->getUri()->getPath())->withStatus(302);
            }
        }

        return $handler->handle($request);
    }
}
