<?php

declare(strict_types=1);

namespace App\Scheduler;

use App\Model\AccountRepository;
use App\Model\RunRepository;
use App\Notify\Notifier;
use Cron\CronExpression;
use DateTimeImmutable;
use PDO;

/**
 * Alerts on the ABSENCE of success, not on failure. Ordinary notifications fire when a run fails, but
 * if the scheduler dies or an account silently stops running there is no failure to report — and the
 * gap stays invisible. This periodically checks each scheduled account: a scheduled fire is due in
 * the past (beyond a grace period) yet there has been no success since. That is exactly the class of
 * silent gap that plain failure alerts miss.
 *
 * Alerts are de-duplicated per account (repeat interval), and an account's alert state is cleared
 * once it recovers, so the next outage alerts promptly.
 */
final class DeadMansSwitch
{
    public function __construct(
        private readonly PDO $pdo,
        private readonly AccountRepository $accounts,
        private readonly RunRepository $runs,
        private readonly Notifier $notifier,
        private readonly int $graceMinutes = 60,
        private readonly int $repeatHours = 24,
    ) {
    }

    /**
     * @return array<int, array<string, mixed>> the scheduled accounts overdue for a success at $now
     */
    public function overdueAccounts(DateTimeImmutable $now): array
    {
        $graceSeconds = $this->graceMinutes * 60;
        $overdue = [];
        foreach ($this->accounts->scheduled() as $account) {
            if (!CronExpression::isValidExpression((string) $account['schedule_cron'])) {
                continue;
            }
            $cron = new CronExpression((string) $account['schedule_cron']);
            $previousDue = DateTimeImmutable::createFromMutable($cron->getPreviousRunDate($now, 0, true));

            // Too soon after the scheduled moment to judge — a run may be in progress right now.
            if ($now->getTimestamp() - $previousDue->getTimestamp() < $graceSeconds) {
                continue;
            }
            $lastSuccess = $this->runs->lastSuccessfulAt((int) $account['id']);
            if ($lastSuccess === null || $lastSuccess < $previousDue) {
                $overdue[] = $account;
            }
        }

        return $overdue;
    }

    /** Send alerts for overdue accounts (de-duplicated) and clear state for recovered ones. */
    public function run(DateTimeImmutable $now): void
    {
        $overdueIds = [];
        foreach ($this->overdueAccounts($now) as $account) {
            $id = (int) $account['id'];
            $overdueIds[$id] = true;
            if ($this->shouldAlert($id, $now)) {
                $this->notifier->send(
                    "⏰ No successful import: {$account['name']}",
                    "The scheduled account \"{$account['name']}\" has not imported successfully when it "
                    . "should have. The scheduler may be down, or the login may need re-authentication."
                );
                $this->recordAlert($id, $now);
            }
        }
        // Recovered accounts: clear their alert state so a future outage alerts immediately.
        $this->pdo->exec('DELETE FROM monitor_state WHERE account_id NOT IN ('
            . ($overdueIds === [] ? '0' : implode(',', array_map('intval', array_keys($overdueIds)))) . ')');
    }

    private function shouldAlert(int $accountId, DateTimeImmutable $now): bool
    {
        $stmt = $this->pdo->prepare('SELECT last_alert_at FROM monitor_state WHERE account_id = ?');
        $stmt->execute([$accountId]);
        $last = $stmt->fetchColumn();
        if ($last === false || $last === null) {
            return true;
        }
        $lastAt = new DateTimeImmutable($last . ' UTC');

        return ($now->getTimestamp() - $lastAt->getTimestamp()) >= $this->repeatHours * 3600;
    }

    private function recordAlert(int $accountId, DateTimeImmutable $now): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO monitor_state (account_id, last_alert_at) VALUES (?, ?)
             ON CONFLICT(account_id) DO UPDATE SET last_alert_at = excluded.last_alert_at'
        );
        $stmt->execute([$accountId, $now->format('Y-m-d H:i:s')]);
    }
}
