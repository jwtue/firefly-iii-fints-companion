<?php

declare(strict_types=1);

namespace App\Http;

use App\Config\ConfigImporter;
use App\Model\AccountRepository;
use App\Model\LoginRepository;
use App\Model\RunRepository;
use App\Scheduler\Scheduler;
use App\Support\Settings;
use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;
use Slim\Views\Twig;

final class DashboardController
{
    public function __construct(
        private readonly Twig $view,
        private readonly LoginRepository $logins,
        private readonly AccountRepository $accounts,
        private readonly RunRepository $runs,
        private readonly Settings $settings,
        private readonly ConfigImporter $importer,
    ) {
    }

    public function index(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        $accounts = $this->accounts->all();
        foreach ($accounts as &$account) {
            $account['last_run'] = $this->runs->lastForAccount((int) $account['id']);
        }
        unset($account);

        $loginCount = count($this->logins->all());
        // On first setup (no logins yet), offer to adopt an existing importer configuration.
        $importable = $loginCount === 0 ? count($this->importer->preview()['accounts']) : 0;

        return $this->view->render($response, 'dashboard.twig', [
            'accounts' => $accounts,
            'login_count' => $loginCount,
            'importable' => $importable,
            'recent_runs' => $this->runs->recent(15),
            'firefly_configured' => $this->settings->get('firefly_url') !== '' && $this->settings->get('firefly_token') !== '',
            'importer_configured' => $this->settings->get('importer_url') !== '',
            'scheduler_enabled' => Scheduler::enabledByEnv(),
            'has_schedules' => (bool) array_filter($accounts, static fn ($a) => ($a['schedule_cron'] ?? '') !== ''),
        ]);
    }
}
