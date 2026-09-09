<?php

declare(strict_types=1);

namespace App\Tests;

use App\Config\ConfigImporter;
use App\Model\AccountRepository;
use App\Model\LoginRepository;
use App\Support\Database;
use App\Support\Settings;
use PDO;
use PHPUnit\Framework\TestCase;

final class ConfigImporterTest extends TestCase
{
    private string $dir;
    private PDO $pdo;
    private ConfigImporter $importer;
    private Settings $settings;

    protected function setUp(): void
    {
        $this->dir = sys_get_temp_dir() . '/cfgimp_' . bin2hex(random_bytes(4));
        mkdir($this->dir, 0o777, true);

        $db = new Database(':memory:');
        $this->pdo = $db->pdo();
        $this->settings = new Settings($this->pdo);
        $this->importer = new ConfigImporter(
            $this->dir,
            new LoginRepository($this->pdo),
            new AccountRepository($this->pdo),
            $this->settings,
        );

        // Two accounts sharing bank login A, one credit card on the same login, one on login B.
        $this->write('giro', 'A', ['bank_account_iban' => 'DE1']);
        $this->write('tagesgeld', 'A', ['bank_account_iban' => 'DE2']);
        $this->write('card', 'A', ['bank_account_number' => '5555']);
        $this->write('other', 'B', ['bank_account_iban' => 'DE9']);
        // Incomplete template (like the shipped example.json): no credentials -> skipped.
        file_put_contents($this->dir . '/example.json', json_encode(['bank_username' => '', 'bank_password' => '']));
    }

    protected function tearDown(): void
    {
        foreach (glob($this->dir . '/*') ?: [] as $f) {
            unlink($f);
        }
        rmdir($this->dir);
    }

    private function write(string $slug, string $login, array $automation): void
    {
        $creds = $login === 'A'
            ? ['bank_code' => '11111111', 'bank_username' => 'userA', 'bank_url' => 'https://a/fints']
            : ['bank_code' => '22222222', 'bank_username' => 'userB', 'bank_url' => 'https://b/fints'];
        $data = $creds + [
            'bank_password' => 'pin' . $login,
            'bank_2fa' => '942',
            'bank_fints_persistence' => 'PERSIST' . $login,
            'firefly_url' => 'http://firefly:8080',
            'firefly_access_token' => 'tok',
            'skip_transaction_review' => 'true',
            'choose_account_automation' => $automation + ['firefly_account_id' => '7', 'from' => 'now - 7 days', 'to' => 'now'],
        ];
        file_put_contents($this->dir . '/' . $slug . '.json', json_encode($data));
    }

    public function test_preview_groups_shared_logins_and_skips_templates(): void
    {
        $plan = $this->importer->preview();

        self::assertCount(2, $plan['logins']);          // login A and login B
        self::assertCount(4, $plan['accounts']);        // giro, tagesgeld, card, other
        self::assertTrue($plan['firefly_token_present']);
        self::assertSame('http://firefly:8080', $plan['firefly_url']);
        self::assertNotEmpty(array_filter($plan['skipped'], static fn ($s) => str_contains($s, 'example.json')));

        // Login A carries three accounts, login B one.
        $counts = array_column($plan['logins'], 'account_count');
        sort($counts);
        self::assertSame([1, 3], $counts);

        // The credit card account is selected by number.
        $card = array_values(array_filter($plan['accounts'], static fn ($a) => $a['slug'] === 'card'))[0];
        self::assertSame('number', $card['selector_type']);
        self::assertSame('5555', $card['bank_account_number']);
    }

    public function test_import_creates_the_model_and_is_idempotent(): void
    {
        $result = $this->importer->import();
        self::assertSame(['logins' => 2, 'accounts' => 4], $result);

        // Firefly connection adopted into global settings.
        self::assertSame('http://firefly:8080', $this->settings->get('firefly_url'));
        self::assertSame('tok', $this->settings->get('firefly_token'));

        // The persistence string round-trips onto the login.
        $logins = (new LoginRepository($this->pdo))->all();
        self::assertContains('PERSISTA', array_column($logins, 'fints_persistence'));

        // Running again imports nothing new.
        self::assertSame(['logins' => 0, 'accounts' => 0], $this->importer->import());
    }
}
