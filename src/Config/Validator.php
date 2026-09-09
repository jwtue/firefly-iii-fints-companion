<?php

declare(strict_types=1);

namespace App\Config;

use Cron\CronExpression;

/**
 * Validates login and account input before it is stored and rendered. The rules encode the
 * importer's real constraints: filenames without spaces (they land unquoted in the trigger URL) and
 * a fetch window of at most 90 days (beyond that PSD2 forces a second TAN mid-dialog that the
 * importer cannot resume).
 */
final class Validator
{
    public const MAX_WINDOW_DAYS = 90;

    /**
     * @param array<string, mixed> $data
     * @return array<string, string> field => message; empty when valid
     */
    public function validateLogin(array $data, bool $isNew): array
    {
        $errors = [];
        foreach (['name', 'bank_url', 'bank_code', 'bank_username'] as $required) {
            if (trim((string) ($data[$required] ?? '')) === '') {
                $errors[$required] = 'err.required';
            }
        }
        // On creation a password is required; on edit an empty field keeps the stored one.
        if ($isNew && trim((string) ($data['bank_password'] ?? '')) === '') {
            $errors['bank_password'] = 'err.required';
        }

        return $errors;
    }

    /**
     * @param array<string, mixed> $data
     * @return array<string, string>
     */
    public function validateAccount(array $data): array
    {
        $errors = [];

        if (trim((string) ($data['name'] ?? '')) === '') {
            $errors['name'] = 'err.required';
        }

        $slug = (string) ($data['slug'] ?? '');
        if (!preg_match('/^[A-Za-z0-9._-]+$/', $slug)) {
            $errors['slug'] = 'err.slug_chars';
        }

        if ((int) ($data['login_id'] ?? 0) <= 0) {
            $errors['login_id'] = 'err.login_required';
        }

        $selector = ($data['selector_type'] ?? 'iban') === 'number' ? 'number' : 'iban';
        if ($selector === 'iban' && trim((string) ($data['bank_account_iban'] ?? '')) === '') {
            $errors['bank_account_iban'] = 'err.iban_required';
        }
        if ($selector === 'number' && trim((string) ($data['bank_account_number'] ?? '')) === '') {
            $errors['bank_account_number'] = 'err.card_number_required';
        }

        if (trim((string) ($data['firefly_account_id'] ?? '')) === '') {
            $errors['firefly_account_id'] = 'err.required';
        }

        $windowError = $this->validateWindow((string) ($data['date_from'] ?? ''), (string) ($data['date_to'] ?? ''));
        if ($windowError !== null) {
            $errors['date_to'] = $windowError;
        }

        $cron = trim((string) ($data['schedule_cron'] ?? ''));
        if ($cron !== '' && !CronExpression::isValidExpression($cron)) {
            $errors['schedule_cron'] = 'err.cron_invalid';
        }

        return $errors;
    }

    private function validateWindow(string $from, string $to): ?string
    {
        if ($from === '' || $to === '') {
            return 'err.window_dates_required';
        }
        // The importer passes these straight into DateTime, so resolve them the same way.
        $fromTs = strtotime($from);
        $toTs = strtotime($to);
        if ($fromTs === false || $toTs === false) {
            return 'err.window_unparseable';
        }
        if ($fromTs > $toTs) {
            return 'err.window_reversed';
        }
        if (($toTs - $fromTs) > self::MAX_WINDOW_DAYS * 86400) {
            return 'err.window_max';
        }

        return null;
    }

    public static function slugify(string $name): string
    {
        $slug = strtolower(trim($name));
        $slug = preg_replace('/[^a-z0-9._-]+/', '-', $slug) ?? '';

        return trim($slug, '-') ?: 'account';
    }
}
