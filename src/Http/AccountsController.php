<?php

declare(strict_types=1);

namespace App\Http;

use App\Config\ConfigSync;
use App\Config\Validator;
use App\Model\AccountRepository;
use App\Model\LoginRepository;
use App\Runner\Runner;
use App\Runner\RunnerBusyException;
use App\Support\Flash;
use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;
use Slim\Views\Twig;
use Throwable;

/** Manages the per-account imports, which inherit their bank access from a login. */
final class AccountsController
{
    public function __construct(
        private readonly Twig $view,
        private readonly AccountRepository $accounts,
        private readonly LoginRepository $logins,
        private readonly Validator $validator,
        private readonly ConfigSync $sync,
        private readonly Runner $runner,
    ) {
    }

    public function index(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        return $this->view->render($response, 'accounts/list.twig', ['accounts' => $this->accounts->all()]);
    }

    public function create(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        return $this->form($response, [
            'selector_type' => 'iban', 'date_from' => 'now - 7 days', 'date_to' => 'now',
            'skip_transaction_review' => 1, 'enabled' => 1,
        ], [], true);
    }

    public function store(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        $data = $this->extract((array) $request->getParsedBody());
        if ($data['slug'] === '') {
            $data['slug'] = Validator::slugify((string) $data['name']);
        }
        $errors = $this->validator->validateAccount($data);
        if (!isset($errors['slug']) && $this->accounts->slugExists((string) $data['slug'])) {
            $errors['slug'] = 'An account with this identifier already exists.';
        }
        if ($errors !== []) {
            return $this->form($response, $data, $errors, true);
        }
        $id = $this->accounts->create($data);
        $this->sync->syncAccount($id);
        Flash::add('success', 'Account created.');

        return $this->redirect($response, '/accounts');
    }

    public function edit(ServerRequestInterface $request, ResponseInterface $response, array $args): ResponseInterface
    {
        $account = $this->accounts->find((int) $args['id']);
        if ($account === null) {
            return $this->redirect($response, '/accounts');
        }

        return $this->form($response, $account, [], false);
    }

    public function update(ServerRequestInterface $request, ResponseInterface $response, array $args): ResponseInterface
    {
        $id = (int) $args['id'];
        $existing = $this->accounts->find($id);
        if ($existing === null) {
            return $this->redirect($response, '/accounts');
        }
        $data = $this->extract((array) $request->getParsedBody());
        if ($data['slug'] === '') {
            $data['slug'] = Validator::slugify((string) $data['name']);
        }
        $errors = $this->validator->validateAccount($data);
        if (!isset($errors['slug']) && $this->accounts->slugExists((string) $data['slug'], $id)) {
            $errors['slug'] = 'An account with this identifier already exists.';
        }
        if ($errors !== []) {
            $data['id'] = $id;

            return $this->form($response, $data, $errors, false);
        }
        // If the slug changed, remove the old rendered file so no stale config lingers.
        if ($existing['slug'] !== $data['slug']) {
            $this->sync->remove((string) $existing['slug']);
        }
        $this->accounts->update($id, $data);
        $this->sync->syncAccount($id);
        Flash::add('success', 'Account updated.');

        return $this->redirect($response, '/accounts');
    }

    public function delete(ServerRequestInterface $request, ResponseInterface $response, array $args): ResponseInterface
    {
        $id = (int) $args['id'];
        $account = $this->accounts->find($id);
        if ($account !== null) {
            $this->sync->remove((string) $account['slug']);
            $this->accounts->delete($id);
            Flash::add('success', 'Account deleted.');
        }

        return $this->redirect($response, '/accounts');
    }

    public function duplicate(ServerRequestInterface $request, ResponseInterface $response, array $args): ResponseInterface
    {
        $account = $this->accounts->find((int) $args['id']);
        if ($account === null) {
            return $this->redirect($response, '/accounts');
        }
        $account['name'] .= ' (copy)';
        $base = Validator::slugify((string) $account['name']);
        $slug = $base;
        $i = 2;
        while ($this->accounts->slugExists($slug)) {
            $slug = $base . '-' . $i++;
        }
        $account['slug'] = $slug;
        $id = $this->accounts->create($account);
        Flash::add('success', 'Account duplicated. Review and save it.');

        return $this->redirect($response, "/accounts/$id/edit");
    }

    public function run(ServerRequestInterface $request, ResponseInterface $response, array $args): ResponseInterface
    {
        $id = (int) $args['id'];
        try {
            $outcome = $this->runner->runAccount($id, 'manual');
            if ($outcome->isSuccess()) {
                Flash::add('success', 'Import finished: ' . $outcome->reason);
            } elseif ($outcome->needsTan()) {
                Flash::add('warning', 'A TAN is required — see the login to re-authenticate.');
            } else {
                Flash::add('error', 'Import failed: ' . $outcome->reason);
            }
        } catch (RunnerBusyException $e) {
            Flash::add('warning', $e->getMessage());
        } catch (Throwable $e) {
            Flash::add('error', 'Could not start the run: ' . $e->getMessage());
        }

        return $this->redirect($response, '/runs');
    }

    /**
     * @param array<string, mixed> $account
     * @param array<string, string> $errors
     */
    private function form(ResponseInterface $response, array $account, array $errors, bool $isNew): ResponseInterface
    {
        return $this->view->render($response, 'accounts/form.twig', [
            'account' => $account,
            'errors' => $errors,
            'is_new' => $isNew,
            'logins' => $this->logins->all(),
        ]);
    }

    /**
     * @param array<string, mixed> $body
     * @return array<string, mixed>
     */
    private function extract(array $body): array
    {
        return [
            'name' => trim((string) ($body['name'] ?? '')),
            'slug' => trim((string) ($body['slug'] ?? '')),
            'login_id' => (int) ($body['login_id'] ?? 0),
            'selector_type' => ($body['selector_type'] ?? 'iban') === 'number' ? 'number' : 'iban',
            'bank_account_iban' => trim((string) ($body['bank_account_iban'] ?? '')),
            'bank_account_number' => trim((string) ($body['bank_account_number'] ?? '')),
            'firefly_account_id' => trim((string) ($body['firefly_account_id'] ?? '')),
            'date_from' => trim((string) ($body['date_from'] ?? 'now - 7 days')),
            'date_to' => trim((string) ($body['date_to'] ?? 'now')),
            'description_regex_match' => (string) ($body['description_regex_match'] ?? ''),
            'description_regex_replace' => (string) ($body['description_regex_replace'] ?? ''),
            'force_mt940' => isset($body['force_mt940']) ? 1 : 0,
            'skip_transaction_review' => isset($body['skip_transaction_review']) ? 1 : 0,
            'schedule_cron' => trim((string) ($body['schedule_cron'] ?? '')),
            'enabled' => isset($body['enabled']) ? 1 : 0,
        ];
    }

    private function redirect(ResponseInterface $response, string $to): ResponseInterface
    {
        return $response->withHeader('Location', $to)->withStatus(302);
    }
}
