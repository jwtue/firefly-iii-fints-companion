<?php

declare(strict_types=1);

namespace App\Config;

use App\Model\AccountRepository;
use App\Model\LoginRepository;
use App\Support\Settings;

/**
 * Adopts an existing importer setup. The importer keeps one self-contained JSON file per account,
 * each repeating the bank credentials. This reads those files and reconstructs the normalized model:
 * files that share the same bank access (URL + code + username) collapse into one login, the
 * account-specific fields become accounts, and the Firefly connection becomes the global setting.
 *
 * The persistence string round-trips verbatim (the importer stores it base64-encoded, which is
 * exactly what a login stores and what {@see ConfigRenderer} emits), so a re-authentication carries
 * over too.
 */
final class ConfigImporter
{
    public function __construct(
        private readonly string $configDir,
        private readonly LoginRepository $logins,
        private readonly AccountRepository $accounts,
        private readonly Settings $settings,
    ) {
    }

    /**
     * Build the adoption plan from the files on disk, without changing anything.
     *
     * @return array{logins: array<int, array<string, mixed>>, accounts: array<int, array<string, mixed>>,
     *     firefly_url: string, firefly_token_present: bool, warnings: string[], skipped: string[], already: string[]}
     */
    public function preview(): array
    {
        $logins = [];   // key => login data (+ account_count)
        $accounts = [];
        $warnings = [];
        $skipped = [];
        $already = [];
        $fireflyUrl = '';
        $fireflyTokenPresent = false;
        $fireflyUrls = [];

        foreach ($this->files() as $path) {
            $slug = basename($path, '.json');
            $data = json_decode((string) file_get_contents($path), true);
            if (!is_array($data)) {
                $skipped[] = basename($path) . ' (not valid JSON)';
                continue;
            }
            // Skip incomplete templates such as the shipped example.json.
            if (trim((string) ($data['bank_username'] ?? '')) === '' || trim((string) ($data['bank_password'] ?? '')) === '') {
                $skipped[] = basename($path) . ' (no credentials)';
                continue;
            }
            if ($this->accounts->findBySlug($slug) !== null) {
                $already[] = $slug;
                continue;
            }

            $key = $this->loginKey($data);
            if (!isset($logins[$key])) {
                $logins[$key] = $this->loginFrom($data) + ['account_count' => 0];
            }
            $logins[$key]['account_count']++;
            $accounts[] = $this->accountFrom($data, $slug, $key);

            $url = trim((string) ($data['firefly_url'] ?? ''));
            if ($url !== '') {
                $fireflyUrls[$url] = true;
                $fireflyUrl = $fireflyUrl ?: $url;
            }
            if (trim((string) ($data['firefly_access_token'] ?? '')) !== '') {
                $fireflyTokenPresent = true;
            }
        }

        if (count($fireflyUrls) > 1) {
            $warnings[] = 'The files reference different Firefly URLs; the first one will be used as the global setting.';
        }

        return [
            'logins' => array_values($logins),
            'accounts' => $accounts,
            'firefly_url' => $fireflyUrl,
            'firefly_token_present' => $fireflyTokenPresent,
            'warnings' => $warnings,
            'skipped' => $skipped,
            'already' => $already,
        ];
    }

    /**
     * Apply the plan: create the logins and accounts, and set the global Firefly connection if it is
     * not already configured. Idempotent — files already represented as accounts are skipped.
     *
     * @return array{logins: int, accounts: int}
     */
    public function import(): array
    {
        // Match existing logins so a re-run (or a partial prior import) does not duplicate them.
        $existing = [];
        foreach ($this->logins->all() as $login) {
            $existing[$this->loginKey($login)] = (int) $login['id'];
        }

        $createdLogins = 0;
        $createdAccounts = 0;
        $firstFireflyUrl = '';
        $firstFireflyToken = '';

        foreach ($this->files() as $path) {
            $slug = basename($path, '.json');
            $data = json_decode((string) file_get_contents($path), true);
            if (!is_array($data)) {
                continue;
            }
            if (trim((string) ($data['bank_username'] ?? '')) === '' || trim((string) ($data['bank_password'] ?? '')) === '') {
                continue;
            }
            if ($this->accounts->findBySlug($slug) !== null) {
                continue;
            }

            $key = $this->loginKey($data);
            if (!isset($existing[$key])) {
                $existing[$key] = $this->logins->create($this->loginFrom($data));
                $createdLogins++;
            }
            $account = $this->accountFrom($data, $slug, $key);
            unset($account['login_key']);
            $account['login_id'] = $existing[$key];
            $account['schedule_cron'] = '';
            $account['enabled'] = 1;
            $this->accounts->create($account);
            $createdAccounts++;

            $firstFireflyUrl = $firstFireflyUrl ?: trim((string) ($data['firefly_url'] ?? ''));
            $firstFireflyToken = $firstFireflyToken ?: trim((string) ($data['firefly_access_token'] ?? ''));
        }

        // Adopt the Firefly connection only if it is not configured yet, so an existing setting wins.
        if ($this->settings->get('firefly_url') === '' && $firstFireflyUrl !== '') {
            $this->settings->set('firefly_url', $firstFireflyUrl);
        }
        if ($this->settings->get('firefly_token') === '' && $firstFireflyToken !== '') {
            $this->settings->set('firefly_token', $firstFireflyToken);
        }

        return ['logins' => $createdLogins, 'accounts' => $createdAccounts];
    }

    /** @return string[] absolute paths of the importer config files */
    private function files(): array
    {
        if (!is_dir($this->configDir)) {
            return [];
        }
        $files = glob(rtrim($this->configDir, '/\\') . DIRECTORY_SEPARATOR . '*.json') ?: [];
        sort($files);

        return $files;
    }

    /** @param array<string, mixed> $data */
    private function loginKey(array $data): string
    {
        return implode('|', [
            (string) ($data['bank_url'] ?? ''),
            (string) ($data['bank_code'] ?? ''),
            (string) ($data['bank_username'] ?? ''),
        ]);
    }

    /**
     * @param array<string, mixed> $data
     * @return array<string, mixed>
     */
    private function loginFrom(array $data): array
    {
        $username = trim((string) ($data['bank_username'] ?? ''));
        $code = trim((string) ($data['bank_code'] ?? ''));

        return [
            'name' => $username !== '' ? "$username ($code)" : "Bank $code",
            'bank_url' => (string) ($data['bank_url'] ?? ''),
            'bank_code' => $code,
            'bank_username' => $username,
            'bank_password' => (string) ($data['bank_password'] ?? ''),
            'bank_2fa' => (string) ($data['bank_2fa'] ?? ''),
            'bank_2fa_device' => (string) ($data['bank_2fa_device'] ?? ''),
            'fints_persistence' => (string) ($data['bank_fints_persistence'] ?? ''),
        ];
    }

    /**
     * @param array<string, mixed> $data
     * @return array<string, mixed>
     */
    private function accountFrom(array $data, string $slug, string $loginKey): array
    {
        $automation = is_array($data['choose_account_automation'] ?? null) ? $data['choose_account_automation'] : [];
        $number = trim((string) ($automation['bank_account_number'] ?? ''));
        $iban = trim((string) ($automation['bank_account_iban'] ?? ''));

        return [
            'login_key' => $loginKey,
            'name' => $slug,
            'slug' => $slug,
            'selector_type' => $number !== '' ? 'number' : 'iban',
            'bank_account_iban' => $iban,
            'bank_account_number' => $number,
            'firefly_account_id' => (string) ($automation['firefly_account_id'] ?? ''),
            'date_from' => (string) ($automation['from'] ?? 'now - 7 days'),
            'date_to' => (string) ($automation['to'] ?? 'now'),
            'description_regex_match' => (string) ($data['description_regex_match'] ?? ''),
            'description_regex_replace' => (string) ($data['description_regex_replace'] ?? ''),
            'force_mt940' => filter_var($data['force_mt940'] ?? false, FILTER_VALIDATE_BOOLEAN) ? 1 : 0,
            'skip_transaction_review' => filter_var($data['skip_transaction_review'] ?? true, FILTER_VALIDATE_BOOLEAN) ? 1 : 0,
        ];
    }
}
