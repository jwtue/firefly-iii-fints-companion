<?php

declare(strict_types=1);

namespace App\Http;

use App\Model\RunRepository;
use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;
use Slim\Views\Twig;

final class RunsController
{
    public function __construct(
        private readonly Twig $view,
        private readonly RunRepository $runs,
    ) {
    }

    public function index(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        return $this->view->render($response, 'runs/list.twig', ['runs' => $this->runs->recent(200)]);
    }

    public function show(ServerRequestInterface $request, ResponseInterface $response, array $args): ResponseInterface
    {
        $run = $this->runs->find((int) $args['id']);
        if ($run === null) {
            return $response->withHeader('Location', '/runs')->withStatus(302);
        }

        return $this->view->render($response, 'runs/detail.twig', ['run' => $run]);
    }
}
