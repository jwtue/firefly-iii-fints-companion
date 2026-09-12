<?php

declare(strict_types=1);

namespace App\Tests;

use App\Config\Schedule;
use PHPUnit\Framework\TestCase;

final class ScheduleTest extends TestCase
{
    public function test_to_cron_off_is_empty(): void
    {
        self::assertSame('', Schedule::toCron(['schedule_freq' => 'off']));
    }

    public function test_to_cron_daily(): void
    {
        self::assertSame('30 6 * * *', Schedule::toCron(['schedule_freq' => 'daily', 'schedule_time' => '06:30']));
    }

    public function test_to_cron_hourly(): void
    {
        self::assertSame('0 * * * *', Schedule::toCron(['schedule_freq' => 'hourly']));
    }

    public function test_to_cron_weekly(): void
    {
        self::assertSame('0 1 * * 3', Schedule::toCron(['schedule_freq' => 'weekly', 'schedule_time' => '01:00', 'schedule_weekday' => '3']));
    }

    public function test_to_cron_custom_passthrough(): void
    {
        self::assertSame('*/15 8-18 * * 1-5', Schedule::toCron(['schedule_freq' => 'custom', 'schedule_cron_custom' => ' */15 8-18 * * 1-5 ']));
    }

    public function test_invalid_time_falls_back(): void
    {
        self::assertSame('0 1 * * *', Schedule::toCron(['schedule_freq' => 'daily', 'schedule_time' => 'nonsense']));
    }

    public function test_from_cron_round_trips(): void
    {
        self::assertSame('off', Schedule::fromCron('')['freq']);
        self::assertSame('hourly', Schedule::fromCron('0 * * * *')['freq']);

        $daily = Schedule::fromCron('30 6 * * *');
        self::assertSame('daily', $daily['freq']);
        self::assertSame('06:30', $daily['time']);

        $weekly = Schedule::fromCron('0 1 * * 3');
        self::assertSame('weekly', $weekly['freq']);
        self::assertSame('01:00', $weekly['time']);
        self::assertSame('3', $weekly['weekday']);

        $custom = Schedule::fromCron('*/15 8-18 * * 1-5');
        self::assertSame('custom', $custom['freq']);
        self::assertSame('*/15 8-18 * * 1-5', $custom['custom']);
    }

    public function test_daily_round_trip_through_both_directions(): void
    {
        $cron = Schedule::toCron(['schedule_freq' => 'daily', 'schedule_time' => '23:05']);
        $back = Schedule::fromCron($cron);
        self::assertSame('daily', $back['freq']);
        self::assertSame('23:05', $back['time']);
    }
}
