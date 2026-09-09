<?php

declare(strict_types=1);

namespace App\Model;

use PDO;

/**
 * A "login" is the shared bank access — URL, code, credentials and the TAN setup — that several
 * account imports have in common. Re-authenticating (a fresh FinTS persistence string, which PSD2
 * forces roughly every 90 days) is done once here and then applies to every account of the login.
 */
final class LoginRepository
{
    private const FIELDS = [
        'name', 'bank_url', 'bank_code', 'bank_username', 'bank_password',
        'bank_2fa', 'bank_2fa_device', 'fints_persistence',
    ];

    public function __construct(private readonly PDO $pdo)
    {
    }

    /** @return array<int, array<string, mixed>> */
    public function all(): array
    {
        return $this->pdo->query('SELECT * FROM logins ORDER BY name COLLATE NOCASE')->fetchAll();
    }

    /** @return array<string, mixed>|null */
    public function find(int $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM logins WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();

        return $row === false ? null : $row;
    }

    /** @param array<string, mixed> $data */
    public function create(array $data): int
    {
        $cols = self::FIELDS;
        $placeholders = implode(', ', array_map(static fn ($c) => ':' . $c, $cols));
        $stmt = $this->pdo->prepare(
            'INSERT INTO logins (' . implode(', ', $cols) . ') VALUES (' . $placeholders . ')'
        );
        $stmt->execute($this->bind($data));

        return (int) $this->pdo->lastInsertId();
    }

    /** @param array<string, mixed> $data */
    public function update(int $id, array $data): void
    {
        $set = implode(', ', array_map(static fn ($c) => "$c = :$c", self::FIELDS));
        $params = $this->bind($data);
        $params['id'] = $id;
        $stmt = $this->pdo->prepare("UPDATE logins SET $set, updated_at = datetime('now') WHERE id = :id");
        $stmt->execute($params);
    }

    public function updatePersistence(int $id, string $persistence): void
    {
        $stmt = $this->pdo->prepare(
            "UPDATE logins
                SET fints_persistence = :p,
                    persistence_updated_at = datetime('now'),
                    updated_at = datetime('now')
              WHERE id = :id"
        );
        $stmt->execute(['p' => $persistence, 'id' => $id]);
    }

    public function delete(int $id): void
    {
        $stmt = $this->pdo->prepare('DELETE FROM logins WHERE id = ?');
        $stmt->execute([$id]);
    }

    public function accountCount(int $id): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) FROM accounts WHERE login_id = ?');
        $stmt->execute([$id]);

        return (int) $stmt->fetchColumn();
    }

    /**
     * @param array<string, mixed> $data
     * @return array<string, mixed>
     */
    private function bind(array $data): array
    {
        $params = [];
        foreach (self::FIELDS as $field) {
            $params[$field] = (string) ($data[$field] ?? '');
        }

        return $params;
    }
}
