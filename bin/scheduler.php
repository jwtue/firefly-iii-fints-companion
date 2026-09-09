<?php

declare(strict_types=1);

use App\Container;
use App\Scheduler\Scheduler;
use Dotenv\Dotenv;

require __DIR__ . '/../vendor/autoload.php';

if (is_file(__DIR__ . '/../.env')) {
    Dotenv::createImmutable(dirname(__DIR__))->safeLoad();
}

/**
 * The scheduler process. It replaces the external cron that used to poke the importer: every minute
 * it runs the account imports whose cron schedule is due, sequentially and through the same run lock
 * as the web UI, so two imports never overlap. Run it as a second container from the same image
 * (command: php bin/scheduler.php) sharing the data volume.
 */
$container = Container::build();
/** @var Scheduler $scheduler */
$scheduler = $container->get(Scheduler::class);

$log = static function (string $message): void {
    fwrite(STDOUT, '[' . gmdate('Y-m-d H:i:s') . 'Z] ' . $message . "\n");
};

$log('Scheduler started.');
$tick = (int) (getenv('SIDECAR_SCHEDULER_INTERVAL') ?: 60);

while (true) {
    try {
        $now = new DateTimeImmutable('now');
        $results = $scheduler->runDue($now);
        foreach ($results as $result) {
            $status = $result['ok'] ? 'ok' : 'FAILED';
            $log("run {$result['account']['name']}: $status ({$result['message']})");
        }
    } catch (Throwable $e) {
        // Never let a single bad tick kill the loop.
        $log('tick error: ' . $e->getMessage());
    }
    sleep(max(5, $tick));
}
