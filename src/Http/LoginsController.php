<?php

declare(strict_types=1);

namespace App\Http;

use App\Config\ConfigSync;
use App\Config\Validator;
use App\Model\AccountRepository;
use App\Model\LoginRepository;
use App\Support\Flash;
use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;
use Slim\Views\Twig;

/**
 * Manages the shared bank logins. Credentials and the TAN setup live here once; the per-account
 * imports inherit them. The re-authentication action updates the FinTS persistence string for the
 * login and re-renders every account that uses it.
 */
final class LoginsController
{
    private const FIELDS = ['name', 'bank_url', 'bank_code', 'bank_username', 'bank_password', 'bank_2fa', 'bank_2fa_device'];

    public function __construct(
        private readonly Twig $view,
        private readonly LoginRepository $logins,
        private readonly AccountRepository $accounts,
        private readonly Validator $validator,
        private readonly ConfigSync $sync,
    ) {
    }

    public function index(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        $logins = $this->logins->all();
        foreach ($logins as &$login) {
            $login['account_count'] = $this->logins->accountCount((int) $login['id']);
        }
        unset($login);

        return $this->view->render($response, 'logins/list.twig', ['logins' => $logins]);
    }

    public function create(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        return $this->view->render($response, 'logins/form.twig', ['login' => [], 'errors' => [], 'is_new' => true]);
    }

    public function store(ServerRequestInterface $request, ResponseInterface $response): ResponseInterface
    {
        $data = $this->extract((array) $request->getParsedBody());
        $errors = $this->validator->validateLogin($data, true);
        if ($errors !== []) {
            return $this->view->render($response, 'logins/form.twig', ['login' => $data, 'errors' => $errors, 'is_new' => true]);
        }
        $this->logins->create($data);
        Flash::add('success', 'Login created.');

        return $this->redirect($response, '/logins');
    }

    public function edit(ServerRequestInterface $request, ResponseInterface $response, array $args): ResponseInterface
    {
        $login = $this->logins->find((int) $args['id']);
        if ($login === null) {
            return $this->redirect($response, '/logins');
        }
        // Never send the stored secret to the browser; an empty field on save keeps it.
        $login['bank_password'] = '';

        return $this->view->render($response, 'logins/form.twig', ['login' => $login, 'errors' => [], 'is_new' => false]);
    }

    public function update(ServerRequestInterface $request, ResponseInterface $response, array $args): ResponseInterface
    {
        $id = (int) $args['id'];
        $existing = $this->logins->find($id);
        if ($existing === null) {
            return $this->redirect($response, '/logins');
        }
        $data = $this->extract((array) $request->getParsedBody());
        $errors = $this->validator->validateLogin($data, false);
        if ($errors !== []) {
            $data['id'] = $id;

            return $this->view->render($response, 'logins/form.twig', ['login' => $data, 'errors' => $errors, 'is_new' => false]);
        }
        // An empty password field keeps the stored password.
        if (trim((string) $data['bank_password']) === '') {
            $data['bank_password'] = $existing['bank_password'];
        }
        // The persistence string is managed through re-authentication, not this form.
        $data['fints_persistence'] = $existing['fints_persistence'];
        $this->logins->update($id, $data);
        $this->sync->syncLogin($id);
        Flash::add('success', 'Login updated.');

        return $this->redirect($response, '/logins');
    }

    public function delete(ServerRequestInterface $request, ResponseInterface $response, array $args): ResponseInterface
    {
        $id = (int) $args['id'];
        // Remove the rendered importer files for the inheriting accounts before the cascade delete.
        foreach ($this->accounts->byLogin($id) as $account) {
            $this->sync->remove((string) $account['slug']);
        }
        $this->logins->delete($id);
        Flash::add('success', 'Login and its accounts deleted.');

        return $this->redirect($response, '/logins');
    }

    public function reauthForm(ServerRequestInterface $request, ResponseInterface $response, array $args): ResponseInterface
    {
        $login = $this->logins->find((int) $args['id']);
        if ($login === null) {
            return $this->redirect($response, '/logins');
        }

        return $this->view->render($response, 'logins/reauth.twig', [
            'login' => $login,
            'account_count' => $this->logins->accountCount((int) $login['id']),
        ]);
    }

    public function reauth(ServerRequestInterface $request, ResponseInterface $response, array $args): ResponseInterface
    {
        $id = (int) $args['id'];
        if ($this->logins->find($id) === null) {
            return $this->redirect($response, '/logins');
        }
        $persistence = trim((string) (((array) $request->getParsedBody())['fints_persistence'] ?? ''));
        if ($persistence === '') {
            Flash::add('error', 'Please paste the persistence string shown by the importer.');

            return $this->redirect($response, "/logins/$id/reauth");
        }
        $this->logins->updatePersistence($id, $persistence);
        $this->sync->syncLogin($id);
        $count = $this->logins->accountCount($id);
        Flash::add('success', "Re-authenticated. $count account(s) updated.");

        return $this->redirect($response, '/logins');
    }

    /**
     * @param array<string, mixed> $body
     * @return array<string, mixed>
     */
    private function extract(array $body): array
    {
        $data = [];
        foreach (self::FIELDS as $field) {
            $data[$field] = trim((string) ($body[$field] ?? ''));
        }

        return $data;
    }

    private function redirect(ResponseInterface $response, string $to): ResponseInterface
    {
        return $response->withHeader('Location', $to)->withStatus(302);
    }
}
