<?php

declare(strict_types=1);

namespace App\Runner;

use App\Config\ConfigRenderer;
use App\Config\ConfigWriter;
use App\Importer\ImporterClient;
use App\Importer\Outcome;
use App\Importer\OutcomeDetector;
use App\Model\AccountRepository;
use App\Model\LoginRepository;
use App\Model\RunRepository;
use App\Notify\Notifier;
use App\Support\Lock;
use App\Support\Redactor;
use App\Support\Settings;
use DateTimeImmutable;
use PDO;
use RuntimeException;

/**
 * Executes one account import end to end: render the importer config from the shared login and the
 * account, write it to the shared directory, trigger the importer, classify the outcome, record the
 * run (with a redacted response excerpt), and notify on anything that is not a clean success.
 */
final class Runner implements RunnerInterface
{
    private const EXCERPT_LIMIT = 4000;

    public function __construct(
        private readonly PDO $pdo,
        private readonly AccountRepository $accounts,
        private readonly LoginRepository $logins,
        private readonly RunRepository $runs,
        private readonly ConfigRenderer $renderer,
        private readonly ConfigWriter $writer,
        private readonly Settings $settings,
        private readonly ImporterClient $importer,
        private readonly OutcomeDetector $detector,
        private readonly Notifier $notifier,
        private readonly Lock $lock,
    ) {
    }

    public function runAccount(int $accountId, string $trigger): Outcome
    {
        $account = $this->accounts->find($accountId);
        if ($account === null) {
            throw new RuntimeException("Account $accountId does not exist.");
        }
        $login = $this->logins->find((int) $account['login_id']);
        if ($login === null) {
            throw new RuntimeException("Account {$account['name']} has no valid login.");
        }

        // After an outage, widen the window for this one run so no transactions are lost.
        $window = CatchUp::effectiveWindow(
            (string) $account['date_from'],
            (string) $account['date_to'],
            $this->runs->lastSuccessfulAt($accountId),
            new DateTimeImmutable('now')
        );
        $effectiveAccount = $account;
        $effectiveAccount['date_from'] = $window['from'];
        $effectiveAccount['date_to'] = $window['to'];

        // (Re)render the flat importer config from the current login + account so a re-authenticated
        // persistence string on the login always reaches the importer.
        $json = $this->renderer->renderJson($login, $effectiveAccount, $this->settings);
        $this->writer->write((string) $account['slug'], $json);

        if (!$this->lock->tryAcquire()) {
            throw new RunnerBusyException('Another import is currently running. Please try again shortly.');
        }

        $runId = $this->runs->start($accountId, (string) $account['name'], (int) $login['id'], $trigger);
        $started = hrtime(true);
        try {
            $response = $this->importer->run($this->writer->fileName((string) $account['slug']));
        } finally {
            $this->lock->release();
        }
        $durationMs = (int) ((hrtime(true) - $started) / 1_000_000);

        $outcome = $this->detector->detect(
            (int) $response['status'],
            (string) $response['body'],
            (string) $response['contentType'],
        );

        $redactor = Redactor::fromDatabase($this->pdo, $this->settings);
        $excerpt = $redactor->redact(mb_substr((string) $response['body'], 0, self::EXCERPT_LIMIT));

        $this->runs->finish(
            $runId,
            $outcome->status,
            $redactor->redact($outcome->reason),
            $response['status'] > 0 ? (int) $response['status'] : null,
            $excerpt,
            $outcome->numTransactions,
            $durationMs,
        );

        if (!$outcome->isSuccess()) {
            $this->notify($account, $login, $outcome);
        }

        return $outcome;
    }

    /**
     * @param array<string, mixed> $account
     * @param array<string, mixed> $login
     */
    private function notify(array $account, array $login, Outcome $outcome): void
    {
        if ($outcome->needsTan()) {
            $title = "🔐 TAN required: {$account['name']}";
            $message = "The login \"{$login['name']}\" needs a fresh TAN.\n"
                . "Run this account once manually through the importer UI, then paste the new "
                . "persistence string into the login — every account under it will use it.";
        } else {
            $title = "❌ Import failed: {$account['name']}";
            $message = "Login \"{$login['name']}\": {$outcome->reason}";
        }
        $this->notifier->send($title, $message);
    }
}
