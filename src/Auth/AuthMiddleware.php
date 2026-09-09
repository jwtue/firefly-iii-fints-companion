<?php

declare(strict_types=1);

namespace App\Auth;

use App\Support\Cidr;
use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;
use Psr\Http\Server\MiddlewareInterface;
use Psr\Http\Server\RequestHandlerInterface;
use Slim\Psr7\Response;

/**
 * Requires a logged-in session for every route except the login form and the unauthenticated
 * liveness probe. Unauthenticated requests are redirected to the login page — unless they arrive
 * from a configured trusted network, evaluated against the DIRECT socket peer only.
 */
final class AuthMiddleware implements MiddlewareInterface
{
    private const PUBLIC_PATHS = ['/login', '/healthz'];

    /** @param string[] $trustedNetworks CIDRs; empty disables the bypass */
    public function __construct(
        private readonly Auth $auth,
        private readonly array $trustedNetworks = [],
    ) {
    }

    public function process(ServerRequestInterface $request, RequestHandlerInterface $handler): ResponseInterface
    {
        $path = $request->getUri()->getPath();
        if ($this->auth->isAuthenticated() || $this->isPublic($path) || $this->isTrustedPeer($request)) {
            return $handler->handle($request);
        }

        return (new Response())->withHeader('Location', '/login')->withStatus(302);
    }

    private function isTrustedPeer(ServerRequestInterface $request): bool
    {
        if ($this->trustedNetworks === []) {
            return false;
        }
        // Deliberately the direct socket peer only — never X-Forwarded-For, which the client controls.
        $peer = (string) ($request->getServerParams()['REMOTE_ADDR'] ?? '');

        return $peer !== '' && Cidr::inAny($peer, $this->trustedNetworks);
    }

    private function isPublic(string $path): bool
    {
        foreach (self::PUBLIC_PATHS as $public) {
            if ($path === $public) {
                return true;
            }
        }

        return str_starts_with($path, '/assets/') || str_starts_with($path, '/lang/');
    }
}
