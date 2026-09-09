<?php

declare(strict_types=1);

namespace App\Tests;

use App\Support\Redactor;
use PHPUnit\Framework\TestCase;

final class RedactorTest extends TestCase
{
    public function test_replaces_known_secrets(): void
    {
        $r = new Redactor(['superSecretPin', 'BASE64PERSISTENCE', 'firefly-token-123']);
        $text = 'PIN=superSecretPin token=firefly-token-123 persist=BASE64PERSISTENCE';
        self::assertSame('PIN=*** token=*** persist=***', $r->redact($text));
    }

    public function test_ignores_short_or_empty_secrets(): void
    {
        // A 2-char value would blank out unrelated text, so it is not treated as a secret; the long
        // one is redacted in every occurrence.
        $r = new Redactor(['ab', '', 'realsecretvalue']);
        self::assertSame('ab stays, *** and *** go', $r->redact('ab stays, realsecretvalue and realsecretvalue go'));
    }

    public function test_empty_input_is_returned_unchanged(): void
    {
        self::assertSame('', (new Redactor(['secretvalue']))->redact(''));
    }
}
