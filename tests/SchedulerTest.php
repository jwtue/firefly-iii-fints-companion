<?php

declare(strict_types=1);

namespace App\Tests;

use App\Importer\Outcome;
use App\Model\AccountRepository;
use App\Model\LoginRepository;
use App\Model\RunRepository;
use App\Runner\RunnerInterface;
use App\Scheduler\Scheduler;
use App\Support\Database;
use DateTimeImmutable;
use PDO;
use PHPUnit\Framework\TestCase;

/** Records which accounts it was asked to run, so the scheduler's decisions can be asserted. */
final class FakeRunner implements RunnerInterface
{
    /** @var int[] */
    public array $calls = [];

    public function runAccount(int $accountId, string $trigger): Outcome
    {
        $this->calls[] = $accountId;

        return new Outcome(Outcome::SUCCESS, 'ok');
    }
}

final class SchedulerTest extends TestCase
{
    private PDO $pdo;
    private AccountRepository $accounts;
    private LoginRepository $logins;
    private RunRepository $runs;
    private FakeRunner $runner;
    private Scheduler $scheduler;
    private int $loginId;

    protected function setUp(): void
    {
        $db = new Database(':memory:');
        $this->pdo = $db->pdo();
        $this->accounts = new AccountRepository($this->pdo);
        $this->logins = new LoginRepository($this->pdo);
        $this->runs = new RunRepository($this->pdo);
        $this->runner = new FakeRunner();
        $this->scheduler = new Scheduler($this->pdo, $this->accounts, $this->runner);
        $this->loginId = $this->logins->create(['name' => 'L', 'bank_url' => 'u', 'bank_code' => 'c', 'bank_username' => 'x', 'bank_password' => 'p']);
    }

    private function account(string $slug, string $cron, int $enabled = 1): int
    {
        return $this->accounts->create([
            'login_id' => $this->loginId, 'name' => $slug, 'slug' => $slug, 'selector_type' => 'iban',
            'bank_account_iban' => 'DE1', 'firefly_account_id' => '1', 'date_from' => 'now - 7 days',
            'date_to' => 'now', 'schedule_cron' => $cron, 'enabled' => $enabled,
        ]);
    }

    public function test_due_when_cron_matches_and_never_run(): void
    {
        $id = $this->account('a', '* * * * *');
        $due = $this->scheduler->dueAccounts(new DateTimeImmutable('now'));
        self::assertSame([$id], array_column($due, 'id'));
    }

    public function test_not_due_after_a_scheduled_run_this_minute(): void
    {
        $id = $this->account('a', '* * * * *');
        $this->runs->start($id, 'a', $this->loginId, 'schedule');
        self::assertSame([], $this->scheduler->dueAccounts(new DateTimeImmutable('now')));
    }

    public function test_manual_run_does_not_satisfy_the_schedule(): void
    {
        $id = $this->account('a', '* * * * *');
        $this->runs->start($id, 'a', $this->loginId, 'manual');
        self::assertSame([$id], array_column($this->scheduler->dueAccounts(new DateTimeImmutable('now')), 'id'));
    }

    public function test_disabled_account_is_never_due(): void
    {
        $this->account('a', '* * * * *', enabled: 0);
        self::assertSame([], $this->scheduler->dueAccounts(new DateTimeImmutable('now')));
    }

    public function test_cron_not_matching_this_minute_is_excluded(): void
    {
        $now = new DateTimeImmutable('now');
        $otherMinute = ((int) $now->format('i') + 30) % 60;
        $this->account('a', "$otherMinute * * * *");
        self::assertSame([], $this->scheduler->dueAccounts($now));
    }

    public function test_enabled_by_env_defaults_on_and_only_false_disables(): void
    {
        putenv('SIDECAR_RUN_SCHEDULER');            // unset → default on
        self::assertTrue(Scheduler::enabledByEnv());
        putenv('SIDECAR_RUN_SCHEDULER=false');
        self::assertFalse(Scheduler::enabledByEnv());
        putenv('SIDECAR_RUN_SCHEDULER=FALSE');      // case-insensitive
        self::assertFalse(Scheduler::enabledByEnv());
        putenv('SIDECAR_RUN_SCHEDULER=true');
        self::assertTrue(Scheduler::enabledByEnv());
        putenv('SIDECAR_RUN_SCHEDULER');            // cleanup
    }

    public function test_runDue_invokes_the_runner_for_due_accounts(): void
    {
        $id = $this->account('a', '* * * * *');
        $results = $this->scheduler->runDue(new DateTimeImmutable('now'));
        self::assertSame([$id], $this->runner->calls);
        self::assertTrue($results[0]['ok']);
    }
}
