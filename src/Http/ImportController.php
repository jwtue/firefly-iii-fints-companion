<?php

declare(strict_types=1);

namespace App\Http;

use App\Config\ConfigImporter;
use App\Support\Flash;
use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;
use Slim\Views\Twig;

/** Adopts an existing importer setup: previews what would be created, then imports it. */
final class ImportController
{
    public function __construct(
        private readonly Twig $view,
        private readonly ConfigImporter $importer,
    ) {
    }

    public function index(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        return $this->view->render($response, 'import.twig', ['plan' => $this->importer->preview()]);
    }

    public function apply(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        $result = $this->importer->import();
        if ($result['logins'] === 0 && $result['accounts'] === 0) {
            Flash::add('warning', 'flash.import_nothing');
        } else {
            Flash::add('success', 'flash.import_done', ['logins' => $result['logins'], 'accounts' => $result['accounts']]);
        }

        return $response->withHeader('Location', '/accounts')->withStatus(302);
    }
}
