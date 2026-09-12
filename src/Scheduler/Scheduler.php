<?php

declare(strict_types=1);

namespace App\Scheduler;

use App\Model\AccountRepository;
use App\Runner\RunnerBusyException;
use App\Runner\RunnerInterface;
use Cron\CronExpression;
use DateTimeImmutable;
use PDO;
use Throwable;

/**
 * Decides which scheduled accounts are due and runs them. Replaces the external cron that used to
 * poke the importer: it owns the schedule, records every run, and (through the runner's lock) never
 * lets two imports overlap.
 *
 * "Due" is derived from the cron expression and the last scheduled run recorded in the history, so a
 * restart of the scheduler process does not re-fire a schedule that already ran this period.
 */
final class Scheduler
{
    public function __construct(
        private readonly PDO $pdo,
        private readonly AccountRepository $accounts,
        private readonly RunnerInterface $runner,
    ) {
    }

    /**
     * Whether the background scheduler is enabled, mirroring the container entrypoint: on by default,
     * off only when SIDECAR_RUN_SCHEDULER is explicitly "false". Lets the UI warn when it is off.
     */
    public static function enabledByEnv(): bool
    {
        return strtolower((string) (getenv('SIDECAR_RUN_SCHEDULER') ?: 'true')) !== 'false';
    }

    /**
     * The scheduled accounts due at $now. An account is due when its cron fires in the current minute
     * and it has not already been run this minute. Deliberately NOT "any missed schedule since the
     * last run": that would fire every schedule once immediately on the first tick after start, which
     * is exactly what we avoid — nothing runs just because the scheduler (re)started. A genuinely
     * missed minute is harmless, since the rolling date window catches the transactions up next time.
     *
     * @return array<int, array<string, mixed>>
     */
    public function dueAccounts(DateTimeImmutable $now): array
    {
        $minuteStart = $now->setTime((int) $now->format('H'), (int) $now->format('i'), 0);
        $due = [];
        foreach ($this->accounts->scheduled() as $account) {
            if (!CronExpression::isValidExpression((string) $account['schedule_cron'])) {
                continue;
            }
            $cron = new CronExpression((string) $account['schedule_cron']);
            if (!$cron->isDue($now)) {
                continue;
            }
            $lastRun = $this->lastScheduledRunAt((int) $account['id']);
            if ($lastRun === null || $lastRun < $minuteStart) {
                $due[] = $account;
            }
        }

        return $due;
    }

    /**
     * Run every account due at $now, sequentially. Failures are isolated per account so one bad run
     * does not stop the rest.
     *
     * @return array<int, array{account: array<string, mixed>, ok: bool, message: string}>
     */
    public function runDue(DateTimeImmutable $now): array
    {
        $results = [];
        foreach ($this->dueAccounts($now) as $account) {
            try {
                $outcome = $this->runner->runAccount((int) $account['id'], 'schedule');
                $results[] = ['account' => $account, 'ok' => $outcome->isSuccess(), 'message' => $outcome->reason];
            } catch (RunnerBusyException $e) {
                // Another run holds the lock; leave this one due so the next tick retries it.
                $results[] = ['account' => $account, 'ok' => false, 'message' => $e->getMessage()];
            } catch (Throwable $e) {
                $results[] = ['account' => $account, 'ok' => false, 'message' => $e->getMessage()];
            }
        }

        return $results;
    }

    private function lastScheduledRunAt(int $accountId): ?DateTimeImmutable
    {
        $stmt = $this->pdo->prepare(
            "SELECT MAX(started_at) FROM runs WHERE account_id = ? AND trigger = 'schedule'"
        );
        $stmt->execute([$accountId]);
        $value = $stmt->fetchColumn();
        if ($value === false || $value === null) {
            return null;
        }

        // runs.started_at is stored as UTC "Y-m-d H:i:s" via SQLite datetime('now').
        return new DateTimeImmutable($value . ' UTC');
    }
}
