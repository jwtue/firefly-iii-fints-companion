<?php

declare(strict_types=1);

namespace App\Tests;

use App\Config\ConfigRenderer;
use App\Support\Database;
use App\Support\Settings;
use PHPUnit\Framework\TestCase;

final class ConfigRendererTest extends TestCase
{
    private Settings $settings;

    protected function setUp(): void
    {
        $db = new Database(':memory:');
        $this->settings = new Settings($db->pdo());
        $this->settings->set('firefly_url', 'http://firefly:8080');
        $this->settings->set('firefly_token', 'the-token');
    }

    private function login(): array
    {
        return [
            'bank_username' => 'user1', 'bank_password' => 'pin', 'bank_code' => '12345678',
            'bank_url' => 'https://bank/fints', 'bank_2fa' => '942', 'bank_2fa_device' => 'phone',
            'fints_persistence' => 'BASE64PERSIST',
        ];
    }

    public function test_renders_iban_account_with_inherited_login_and_global_firefly(): void
    {
        $account = [
            'selector_type' => 'iban', 'bank_account_iban' => 'DE111', 'firefly_account_id' => '7',
            'date_from' => 'now - 7 days', 'date_to' => 'now', 'skip_transaction_review' => 1,
            'force_mt940' => 0, 'description_regex_match' => '', 'description_regex_replace' => '',
        ];

        $out = (new ConfigRenderer())->render($this->login(), $account, $this->settings);

        // Inherited from the login.
        self::assertSame('user1', $out['bank_username']);
        self::assertSame('pin', $out['bank_password']);
        self::assertSame('BASE64PERSIST', $out['bank_fints_persistence']);
        // Global Firefly connection.
        self::assertSame('http://firefly:8080', $out['firefly_url']);
        self::assertSame('the-token', $out['firefly_access_token']);
        // Account-specific.
        self::assertSame('DE111', $out['choose_account_automation']['bank_account_iban']);
        self::assertArrayNotHasKey('bank_account_number', $out['choose_account_automation']);
        self::assertSame('7', $out['choose_account_automation']['firefly_account_id']);
        // Importer type quirks: string boolean, real boolean.
        self::assertSame('true', $out['skip_transaction_review']);
        self::assertFalse($out['force_mt940']);
        self::assertFalse($out['auto_submit_form_via_js']);
    }

    public function test_credit_card_account_is_selected_by_number(): void
    {
        $account = [
            'selector_type' => 'number', 'bank_account_number' => '5555000011112222',
            'firefly_account_id' => '9', 'date_from' => 'now - 30 days', 'date_to' => 'now',
            'skip_transaction_review' => 0, 'force_mt940' => 1,
        ];

        $out = (new ConfigRenderer())->render($this->login(), $account, $this->settings);

        self::assertSame('5555000011112222', $out['choose_account_automation']['bank_account_number']);
        self::assertArrayNotHasKey('bank_account_iban', $out['choose_account_automation']);
        self::assertSame('false', $out['skip_transaction_review']);
        self::assertTrue($out['force_mt940']);
    }

    public function test_json_is_valid_and_pretty(): void
    {
        $json = (new ConfigRenderer())->renderJson($this->login(), [
            'selector_type' => 'iban', 'bank_account_iban' => 'DE1', 'firefly_account_id' => '1',
        ], $this->settings);

        self::assertJson($json);
        $decoded = json_decode($json, true);
        self::assertSame('DE1', $decoded['choose_account_automation']['bank_account_iban']);
    }
}
