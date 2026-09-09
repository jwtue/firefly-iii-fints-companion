<?php

declare(strict_types=1);

namespace App\Config;

use App\Model\AccountRepository;
use App\Model\LoginRepository;
use App\Support\Settings;

/**
 * Keeps the importer's flat config files in step with the normalized model. The runner re-renders
 * before every run anyway, but syncing eagerly on every edit keeps the files current for a manual
 * importer session and makes a re-authentication visibly propagate to all inheriting accounts.
 */
final class ConfigSync
{
    public function __construct(
        private readonly LoginRepository $logins,
        private readonly AccountRepository $accounts,
        private readonly ConfigRenderer $renderer,
        private readonly ConfigWriter $writer,
        private readonly Settings $settings,
    ) {
    }

    public function syncAccount(int $accountId): void
    {
        $account = $this->accounts->find($accountId);
        if ($account === null) {
            return;
        }
        $login = $this->logins->find((int) $account['login_id']);
        if ($login === null) {
            return;
        }
        $this->writer->write(
            (string) $account['slug'],
            $this->renderer->renderJson($login, $account, $this->settings)
        );
    }

    /** Re-render every account that inherits from a login (used after a re-authentication). */
    public function syncLogin(int $loginId): void
    {
        foreach ($this->accounts->byLogin($loginId) as $account) {
            $this->syncAccount((int) $account['id']);
        }
    }

    public function remove(string $slug): void
    {
        $this->writer->delete($slug);
    }
}
