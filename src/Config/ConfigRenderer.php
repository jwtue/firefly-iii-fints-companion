<?php

declare(strict_types=1);

namespace App\Config;

use App\Support\Settings;

/**
 * Renders the importer's flat, self-contained configuration JSON from the normalized model: the
 * shared login, the account-specific fields and the global Firefly connection.
 *
 * This is the bridge between the two data models. The importer knows nothing about shared logins;
 * it reads one JSON file per account with every field inlined. The sidecar owns those files and
 * regenerates them from this store — so a single re-authentication on a login propagates to every
 * account that inherits from it.
 */
final class ConfigRenderer
{
    /**
     * @param array<string, mixed> $login   a row from the logins table
     * @param array<string, mixed> $account a row from the accounts table
     * @return array<string, mixed> the importer configuration, ready to be JSON-encoded
     */
    public function render(array $login, array $account, Settings $settings): array
    {
        $selectorType = ($account['selector_type'] ?? 'iban') === 'number' ? 'number' : 'iban';
        $automation = [
            'firefly_account_id' => (string) ($account['firefly_account_id'] ?? ''),
            'from'               => (string) ($account['date_from'] ?? 'now - 7 days'),
            'to'                 => (string) ($account['date_to'] ?? 'now'),
        ];
        // A regular account is selected by IBAN, a credit card account by its account number.
        if ($selectorType === 'number') {
            $automation['bank_account_number'] = (string) ($account['bank_account_number'] ?? '');
        } else {
            $automation['bank_account_iban'] = (string) ($account['bank_account_iban'] ?? '');
        }

        return [
            'bank_username'           => (string) ($login['bank_username'] ?? ''),
            'bank_password'           => (string) ($login['bank_password'] ?? ''),
            'bank_code'               => (string) ($login['bank_code'] ?? ''),
            'bank_url'                => (string) ($login['bank_url'] ?? ''),
            'bank_2fa'                => (string) ($login['bank_2fa'] ?? ''),
            'bank_2fa_device'         => (string) ($login['bank_2fa_device'] ?? ''),
            // The importer base64-decodes this field; the string stored here is exactly what the
            // importer displayed after a successful run, which is already base64-encoded.
            'bank_fints_persistence'  => (string) ($login['fints_persistence'] ?? ''),
            'firefly_url'             => $settings->get('firefly_url'),
            'firefly_access_token'    => $settings->get('firefly_token'),
            // The importer expects a string boolean here (filter_var VALIDATE_BOOLEAN).
            'skip_transaction_review' => ((int) ($account['skip_transaction_review'] ?? 1)) === 1 ? 'true' : 'false',
            'description_regex_match'   => (string) ($account['description_regex_match'] ?? ''),
            'description_regex_replace' => (string) ($account['description_regex_replace'] ?? ''),
            // Headless runs are driven server-side, never through the JS auto-submit path.
            'auto_submit_form_via_js' => false,
            'force_mt940'             => ((int) ($account['force_mt940'] ?? 0)) === 1,
            'choose_account_automation' => $automation,
        ];
    }

    /** @param array<string, mixed> $login @param array<string, mixed> $account */
    public function renderJson(array $login, array $account, Settings $settings): string
    {
        return json_encode(
            $this->render($login, $account, $settings),
            JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
        );
    }
}
