<?php

declare(strict_types=1);

namespace App\Tests;

use App\Runner\CatchUp;
use DateTimeImmutable;
use PHPUnit\Framework\TestCase;

final class CatchUpTest extends TestCase
{
    private DateTimeImmutable $now;

    protected function setUp(): void
    {
        $this->now = new DateTimeImmutable('2026-01-31 12:00:00');
    }

    public function test_first_run_uses_the_configured_window(): void
    {
        $w = CatchUp::effectiveWindow('now - 7 days', 'now', null, $this->now);
        self::assertFalse($w['widened']);
        self::assertSame('now - 7 days', $w['from']);
    }

    public function test_recent_success_keeps_the_normal_window(): void
    {
        $lastSuccess = $this->now->modify('-3 days');
        $w = CatchUp::effectiveWindow('now - 7 days', 'now', $lastSuccess, $this->now);
        self::assertFalse($w['widened']);
        self::assertSame('now - 7 days', $w['from']);
    }

    public function test_outage_beyond_window_widens_for_one_run(): void
    {
        $lastSuccess = $this->now->modify('-20 days');
        $w = CatchUp::effectiveWindow('now - 7 days', 'now', $lastSuccess, $this->now);
        self::assertTrue($w['widened']);
        // 20 days ago + one day buffer.
        self::assertSame('now - 21 days', $w['from']);
        self::assertSame('now', $w['to']);
    }

    public function test_widening_is_capped_at_the_psd2_limit(): void
    {
        $lastSuccess = $this->now->modify('-200 days');
        $w = CatchUp::effectiveWindow('now - 7 days', 'now', $lastSuccess, $this->now);
        self::assertTrue($w['widened']);
        self::assertSame('now - 90 days', $w['from']);
    }
}
