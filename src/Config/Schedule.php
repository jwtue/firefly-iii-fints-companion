<?php

declare(strict_types=1);

namespace App\Config;

/**
 * Translates between a friendly schedule form (frequency + time + weekday) and the cron expression
 * stored in the account. The scheduler keeps working on cron; only the UI is friendlier. A raw cron
 * string is still available as the "custom" escape hatch, and any cron the friendly form cannot
 * represent is round-tripped through "custom".
 */
final class Schedule
{
    public const FREQUENCIES = ['off', 'hourly', 'daily', 'weekly', 'custom'];
    private const DEFAULT_TIME = '01:00';
    private const DEFAULT_WEEKDAY = '1'; // Monday (cron day-of-week: 0=Sun … 6=Sat)

    /**
     * @param array<string, mixed> $in form fields: schedule_freq, schedule_time, schedule_weekday, schedule_cron_custom
     */
    public static function toCron(array $in): string
    {
        $freq = in_array($in['schedule_freq'] ?? 'off', self::FREQUENCIES, true)
            ? (string) $in['schedule_freq'] : 'off';
        [$h, $m] = self::parseTime((string) ($in['schedule_time'] ?? self::DEFAULT_TIME));
        $dow = (string) ($in['schedule_weekday'] ?? self::DEFAULT_WEEKDAY);
        if (preg_match('/^[0-6]$/', $dow) !== 1) {
            $dow = self::DEFAULT_WEEKDAY;
        }

        return match ($freq) {
            'hourly' => '0 * * * *',
            'daily' => "$m $h * * *",
            'weekly' => "$m $h * * $dow",
            'custom' => trim((string) ($in['schedule_cron_custom'] ?? '')),
            default => '',
        };
    }

    /**
     * @return array{freq: string, time: string, weekday: string, custom: string}
     */
    public static function fromCron(string $cron): array
    {
        $cron = trim($cron);
        $default = ['freq' => 'off', 'time' => self::DEFAULT_TIME, 'weekday' => self::DEFAULT_WEEKDAY, 'custom' => ''];

        if ($cron === '') {
            return $default;
        }
        if ($cron === '0 * * * *') {
            return ['freq' => 'hourly'] + $default;
        }
        if (preg_match('/^(\d{1,2}) (\d{1,2}) \* \* \*$/', $cron, $mm) === 1) {
            return ['freq' => 'daily', 'time' => self::fmtTime((int) $mm[2], (int) $mm[1]), 'weekday' => self::DEFAULT_WEEKDAY, 'custom' => ''];
        }
        if (preg_match('/^(\d{1,2}) (\d{1,2}) \* \* ([0-6])$/', $cron, $mm) === 1) {
            return ['freq' => 'weekly', 'time' => self::fmtTime((int) $mm[2], (int) $mm[1]), 'weekday' => $mm[3], 'custom' => ''];
        }

        return ['freq' => 'custom', 'time' => self::DEFAULT_TIME, 'weekday' => self::DEFAULT_WEEKDAY, 'custom' => $cron];
    }

    /** @return array{0:int,1:int} [hour, minute] */
    private static function parseTime(string $time): array
    {
        if (preg_match('/^(\d{1,2}):(\d{2})$/', trim($time), $m) === 1) {
            $h = min(23, max(0, (int) $m[1]));
            $min = min(59, max(0, (int) $m[2]));

            return [$h, $min];
        }

        return [1, 0];
    }

    private static function fmtTime(int $hour, int $minute): string
    {
        return sprintf('%02d:%02d', min(23, max(0, $hour)), min(59, max(0, $minute)));
    }
}
