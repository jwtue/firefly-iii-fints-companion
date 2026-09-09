<?php

declare(strict_types=1);

namespace App\Runner;

use App\Importer\Outcome;

interface RunnerInterface
{
    /**
     * Execute one account import.
     *
     * @param string $trigger 'manual' or 'schedule'
     * @throws RunnerBusyException when another import holds the run lock
     */
    public function runAccount(int $accountId, string $trigger): Outcome;
}
