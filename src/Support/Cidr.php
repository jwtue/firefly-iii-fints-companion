<?php

declare(strict_types=1);

namespace App\Support;

/**
 * IP-in-CIDR matching for the trusted-network auth bypass. Supports IPv4 and IPv6.
 *
 * Security note: callers must only ever pass the DIRECT socket peer (REMOTE_ADDR) here, never a
 * value derived from X-Forwarded-For or any other client-supplied header — those are trivially
 * spoofable. Behind a reverse proxy the peer is the proxy itself, so trusting a network here trusts
 * everything arriving through that proxy.
 */
final class Cidr
{
    /** @param string[] $cidrs */
    public static function inAny(string $ip, array $cidrs): bool
    {
        foreach ($cidrs as $cidr) {
            $cidr = trim($cidr);
            if ($cidr !== '' && self::matches($ip, $cidr)) {
                return true;
            }
        }

        return false;
    }

    public static function matches(string $ip, string $cidr): bool
    {
        if (!str_contains($cidr, '/')) {
            return $ip === $cidr;
        }
        [$subnet, $bits] = explode('/', $cidr, 2);
        $bits = (int) $bits;

        $ipBin = @inet_pton($ip);
        $subnetBin = @inet_pton($subnet);
        if ($ipBin === false || $subnetBin === false || strlen($ipBin) !== strlen($subnetBin)) {
            return false; // mismatched families or invalid input
        }

        $bytes = intdiv($bits, 8);
        $remainder = $bits % 8;

        if ($bytes > 0 && strncmp($ipBin, $subnetBin, $bytes) !== 0) {
            return false;
        }
        if ($remainder === 0) {
            return true;
        }
        $mask = chr((0xFF << (8 - $remainder)) & 0xFF);

        return (ord($ipBin[$bytes]) & ord($mask)) === (ord($subnetBin[$bytes]) & ord($mask));
    }

    /** @return string[] */
    public static function parseList(string $csv): array
    {
        return array_values(array_filter(array_map('trim', explode(',', $csv)), static fn ($c) => $c !== ''));
    }
}
