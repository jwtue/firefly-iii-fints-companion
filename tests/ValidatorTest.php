<?php

declare(strict_types=1);

namespace App\Tests;

use App\Config\Validator;
use PHPUnit\Framework\TestCase;

final class ValidatorTest extends TestCase
{
    private Validator $validator;

    protected function setUp(): void
    {
        $this->validator = new Validator();
    }

    private function validAccount(array $overrides = []): array
    {
        return array_merge([
            'name' => 'Checking', 'slug' => 'checking', 'login_id' => 1, 'selector_type' => 'iban',
            'bank_account_iban' => 'DE111', 'bank_account_number' => '', 'firefly_account_id' => '3',
            'date_from' => 'now - 7 days', 'date_to' => 'now', 'schedule_cron' => '0 1 * * *',
        ], $overrides);
    }

    public function test_valid_account_has_no_errors(): void
    {
        self::assertSame([], $this->validator->validateAccount($this->validAccount()));
    }

    public function test_slug_with_spaces_is_rejected(): void
    {
        $errors = $this->validator->validateAccount($this->validAccount(['slug' => 'has space']));
        self::assertArrayHasKey('slug', $errors);
    }

    public function test_window_over_ninety_days_is_rejected(): void
    {
        $errors = $this->validator->validateAccount($this->validAccount(['date_from' => 'now - 120 days']));
        self::assertArrayHasKey('date_to', $errors);
    }

    public function test_reversed_window_is_rejected(): void
    {
        $errors = $this->validator->validateAccount($this->validAccount([
            'date_from' => 'now', 'date_to' => 'now - 7 days',
        ]));
        self::assertArrayHasKey('date_to', $errors);
    }

    public function test_credit_card_requires_account_number(): void
    {
        $errors = $this->validator->validateAccount($this->validAccount([
            'selector_type' => 'number', 'bank_account_iban' => '', 'bank_account_number' => '',
        ]));
        self::assertArrayHasKey('bank_account_number', $errors);
    }

    public function test_invalid_cron_is_rejected(): void
    {
        $errors = $this->validator->validateAccount($this->validAccount(['schedule_cron' => 'not a cron']));
        self::assertArrayHasKey('schedule_cron', $errors);
    }

    public function test_empty_cron_is_allowed(): void
    {
        $errors = $this->validator->validateAccount($this->validAccount(['schedule_cron' => '']));
        self::assertArrayNotHasKey('schedule_cron', $errors);
    }

    public function test_slugify(): void
    {
        self::assertSame('bw-bank-giro', Validator::slugify('BW-Bank Giro'));
        self::assertSame('account', Validator::slugify('   '));
    }
}
