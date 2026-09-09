<?php

declare(strict_types=1);

namespace App\Auth;

use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;
use Psr\Http\Server\MiddlewareInterface;
use Psr\Http\Server\RequestHandlerInterface;
use Slim\Psr7\Response;

/**
 * Requires a logged-in session for every route except the login form and the unauthenticated
 * liveness probe. Unauthenticated requests are redirected to the login page.
 */
final class AuthMiddleware implements MiddlewareInterface
{
    private const PUBLIC_PATHS = ['/login', '/healthz'];

    public function __construct(private readonly Auth $auth)
    {
    }

    public function process(ServerRequestInterface $request, RequestHandlerInterface $handler): ResponseInterface
    {
        $path = $request->getUri()->getPath();
        if ($this->auth->isAuthenticated() || $this->isPublic($path)) {
            return $handler->handle($request);
        }

        $response = new Response();

        return $response
            ->withHeader('Location', '/login')
            ->withStatus(302);
    }

    private function isPublic(string $path): bool
    {
        foreach (self::PUBLIC_PATHS as $public) {
            if ($path === $public) {
                return true;
            }
        }

        return str_starts_with($path, '/assets/');
    }
}
