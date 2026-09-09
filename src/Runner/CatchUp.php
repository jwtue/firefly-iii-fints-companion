<?php

declare(strict_types=1);

namespace App\Runner;

use App\Config\Validator;
use DateTimeImmutable;

/**
 * Widens the fetch window for a single run after an outage, so no transactions are lost.
 *
 * The normal window is rolling (e.g. "now - 7 days" .. "now"). If the last successful run is further
 * back than that window spans, the days in between would never be fetched. This computes a one-off
 * start date that reaches back to (just before) the last success, capped at the 90-day PSD2 limit.
 * Firefly's duplicate detection absorbs the overlap, so widening is always safe. The normal window
 * is left untouched in storage; only this run uses the widened one.
 */
final class CatchUp
{
    /**
     * @return array{from: string, to: string, widened: bool}
     */
    public static function effectiveWindow(
        string $dateFrom,
        string $dateTo,
        ?DateTimeImmutable $lastSuccess,
        DateTimeImmutable $now
    ): array {
        $normal = ['from' => $dateFrom, 'to' => $dateTo, 'widened' => false];

        // First-ever run (no prior success): use the configured window as-is.
        if ($lastSuccess === null) {
            return $normal;
        }

        $base = $now->getTimestamp();
        $fromTs = strtotime($dateFrom, $base);
        $toTs = strtotime($dateTo, $base);
        if ($fromTs === false || $toTs === false || $toTs <= $fromTs) {
            return $normal;
        }

        $spanSeconds = $toTs - $fromTs;
        $gapSeconds = $base - $lastSuccess->getTimestamp();

        // The normal window already covers the time since the last success — nothing to do.
        if ($gapSeconds <= $spanSeconds) {
            return $normal;
        }

        // Reach back to just before the last success, with a one-day buffer, capped at the PSD2 limit.
        $neededDays = (int) ceil($gapSeconds / 86400) + 1;
        $neededDays = min($neededDays, Validator::MAX_WINDOW_DAYS);

        return ['from' => "now - {$neededDays} days", 'to' => $dateTo, 'widened' => true];
    }
}
