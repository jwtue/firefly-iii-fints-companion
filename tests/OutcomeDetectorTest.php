<?php

declare(strict_types=1);

namespace App\Tests;

use App\Importer\Outcome;
use App\Importer\OutcomeDetector;
use PHPUnit\Framework\TestCase;

final class OutcomeDetectorTest extends TestCase
{
    private OutcomeDetector $detector;

    protected function setUp(): void
    {
        $this->detector = new OutcomeDetector();
    }

    public function test_json_success_with_transaction_count(): void
    {
        $o = $this->detector->detect(200, '{"status":"ok","transactions":5}', 'application/json');
        self::assertSame(Outcome::SUCCESS, $o->status);
        self::assertSame(5, $o->numTransactions);
        self::assertSame('json', $o->source);
    }

    public function test_json_tan_required(): void
    {
        $o = $this->detector->detect(409, '{"status":"tan_required"}', 'application/json');
        self::assertSame(Outcome::TAN_REQUIRED, $o->status);
    }

    public function test_http_status_without_json_body(): void
    {
        self::assertSame(Outcome::TAN_REQUIRED, $this->detector->detect(409, '<html>...</html>')->status);
        self::assertSame(Outcome::FAILURE, $this->detector->detect(404, '<html>...</html>')->status);
        self::assertSame(Outcome::FAILURE, $this->detector->detect(500, '<html>...</html>')->status);
    }

    public function test_html_success_page(): void
    {
        $body = '<h1>Import finished</h1><p>12 transactions have been sent to Firefly III.</p>';
        $o = $this->detector->detect(200, $body);
        self::assertSame(Outcome::SUCCESS, $o->status);
        self::assertSame(12, $o->numTransactions);
        self::assertSame('html', $o->source);
    }

    public function test_html_config_not_found_is_a_failure_not_a_silent_success(): void
    {
        // This is the exact class of page that made a body-grep report success for runs that
        // never happened: HTTP 200, no "Fatal error" string.
        $body = '<h1>Could not find the configuration</h1><p>...</p>';
        $o = $this->detector->detect(200, $body);
        self::assertSame(Outcome::FAILURE, $o->status);
        self::assertStringContainsString('Could not find the configuration', $o->reason);
    }

    public function test_html_fatal_error(): void
    {
        $o = $this->detector->detect(200, 'Fatal error: something broke in /app/index.php');
        self::assertSame(Outcome::FAILURE, $o->status);
    }

    public function test_html_tan_challenge(): void
    {
        $o = $this->detector->detect(200, '<h1>Enter TAN</h1><p>The bank requested a TAN</p>');
        self::assertSame(Outcome::TAN_REQUIRED, $o->status);
    }

    public function test_unrecognized_html_defaults_to_failure(): void
    {
        $o = $this->detector->detect(200, '<h1>Some unknown interactive page</h1>');
        self::assertSame(Outcome::FAILURE, $o->status);
    }
}
