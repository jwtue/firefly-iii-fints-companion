<?php

declare(strict_types=1);

namespace App\Tests;

use App\Support\Cidr;
use PHPUnit\Framework\TestCase;

final class CidrTest extends TestCase
{
    public function test_ipv4_within_and_outside_range(): void
    {
        self::assertTrue(Cidr::matches('192.168.1.50', '192.168.1.0/24'));
        self::assertFalse(Cidr::matches('192.168.2.50', '192.168.1.0/24'));
        self::assertTrue(Cidr::matches('10.1.2.3', '10.0.0.0/8'));
        self::assertFalse(Cidr::matches('11.0.0.1', '10.0.0.0/8'));
    }

    public function test_exact_ip_without_mask(): void
    {
        self::assertTrue(Cidr::matches('127.0.0.1', '127.0.0.1'));
        self::assertFalse(Cidr::matches('127.0.0.2', '127.0.0.1'));
    }

    public function test_ipv6(): void
    {
        self::assertTrue(Cidr::matches('2001:db8::1', '2001:db8::/32'));
        self::assertFalse(Cidr::matches('2001:db9::1', '2001:db8::/32'));
    }

    public function test_mismatched_families_do_not_match(): void
    {
        self::assertFalse(Cidr::matches('192.168.1.1', '2001:db8::/32'));
    }

    public function test_in_any_and_parse_list(): void
    {
        $nets = Cidr::parseList(' 10.0.0.0/8 , 192.168.0.0/16 ,, ');
        self::assertSame(['10.0.0.0/8', '192.168.0.0/16'], $nets);
        self::assertTrue(Cidr::inAny('192.168.5.5', $nets));
        self::assertFalse(Cidr::inAny('172.16.0.1', $nets));
    }
}
