<?php

declare(strict_types=1);

namespace App\Tests;

use App\Model\AccountRepository;
use App\Model\LoginRepository;
use App\Model\RunRepository;
use App\Notify\Notifier;
use App\Scheduler\DeadMansSwitch;
use App\Support\Database;
use DateTimeImmutable;
use PDO;
use PHPUnit\Framework\TestCase;

/** Counts deliveries so alert de-duplication can be asserted. */
final class CountingNotifier implements Notifier
{
    public int $sends = 0;

    public function isConfigured(): bool
    {
        return true;
    }

    public function send(string $title, string $message): void
    {
        $this->sends++;
    }

    public function test(): array
    {
        return ['ok' => true, 'detail' => ''];
    }
}

final class DeadMansSwitchTest extends TestCase
{
    private PDO $pdo;
    private AccountRepository $accounts;
    private RunRepository $runs;
    private CountingNotifier $notifier;
    private DeadMansSwitch $switch;
    private int $loginId;

    protected function setUp(): void
    {
        $db = new Database(':memory:');
        $this->pdo = $db->pdo();
        $this->accounts = new AccountRepository($this->pdo);
        $this->runs = new RunRepository($this->pdo);
        $this->notifier = new CountingNotifier();
        // grace 0 so an every-minute schedule is immediately judgeable in the test.
        $this->switch = new DeadMansSwitch($this->pdo, $this->accounts, $this->runs, $this->notifier, 0, 24);
        $logins = new LoginRepository($this->pdo);
        $this->loginId = $logins->create(['name' => 'L', 'bank_url' => 'u', 'bank_code' => 'c', 'bank_username' => 'x', 'bank_password' => 'p']);
    }

    private function account(string $slug, string $cron, int $enabled = 1): int
    {
        return $this->accounts->create([
            'login_id' => $this->loginId, 'name' => $slug, 'slug' => $slug, 'selector_type' => 'iban',
            'bank_account_iban' => 'DE1', 'firefly_account_id' => '1', 'schedule_cron' => $cron, 'enabled' => $enabled,
        ]);
    }

    public function test_overdue_when_scheduled_but_never_succeeded(): void
    {
        $id = $this->account('a', '* * * * *');
        self::assertSame([$id], array_column($this->switch->overdueAccounts(new DateTimeImmutable('now')), 'id'));
    }

    public function test_not_overdue_after_a_recent_success(): void
    {
        $id = $this->account('a', '* * * * *');
        $runId = $this->runs->start($id, 'a', $this->loginId, 'schedule');
        $this->runs->finish($runId, 'success', 'ok', 200, '', 3, 100);
        self::assertSame([], $this->switch->overdueAccounts(new DateTimeImmutable('now')));
    }

    public function test_disabled_account_is_not_monitored(): void
    {
        $this->account('a', '* * * * *', enabled: 0);
        self::assertSame([], $this->switch->overdueAccounts(new DateTimeImmutable('now')));
    }

    public function test_alert_is_sent_once_then_deduplicated(): void
    {
        $this->account('a', '* * * * *');
        $now = new DateTimeImmutable('now');
        $this->switch->run($now);
        $this->switch->run($now);
        self::assertSame(1, $this->notifier->sends);
    }

    public function test_recovery_clears_alert_state(): void
    {
        $id = $this->account('a', '* * * * *');
        $now = new DateTimeImmutable('now');
        $this->switch->run($now);                 // overdue -> alert, state stored
        self::assertSame(1, $this->notifier->sends);

        $runId = $this->runs->start($id, 'a', $this->loginId, 'schedule');
        $this->runs->finish($runId, 'success', 'ok', 200, '', 1, 10);
        $this->switch->run($now);                 // recovered -> state cleared, no alert
        self::assertSame(1, $this->notifier->sends);

        // A fresh outage (delete the success) should alert again immediately, not wait for the repeat window.
        $this->pdo->exec('DELETE FROM runs');
        $this->switch->run($now);
        self::assertSame(2, $this->notifier->sends);
    }
}
