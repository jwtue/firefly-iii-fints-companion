<?php

declare(strict_types=1);

namespace App\Http;

use App\Auth\Auth;
use App\Support\Flash;
use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;
use Slim\Views\Twig;

final class AuthController
{
    public function __construct(
        private readonly Twig $view,
        private readonly Auth $auth,
    ) {
    }

    public function showLogin(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        if ($this->auth->isAuthenticated()) {
            return $response->withHeader('Location', '/')->withStatus(302);
        }

        return $this->view->render($response, 'login.twig', ['show_nav' => false]);
    }

    public function login(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        $password = (string) (((array) $request->getParsedBody())['password'] ?? '');
        if ($this->auth->attempt($password)) {
            return $response->withHeader('Location', '/')->withStatus(302);
        }
        Flash::add('error', 'flash.wrong_password');

        return $response->withHeader('Location', '/login')->withStatus(302);
    }

    public function logout(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        $this->auth->logout();

        return $response->withHeader('Location', '/login')->withStatus(302);
    }
}
