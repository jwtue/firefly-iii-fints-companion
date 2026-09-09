<?php

declare(strict_types=1);

namespace App\Model;

use PDO;

/**
 * An account import inherits its bank access from a {@see LoginRepository login} and adds only the
 * account-specific parts: which account to fetch (IBAN or, for credit cards, account number), the
 * Firefly target account, the rolling date window, description rewriting and a schedule.
 */
final class AccountRepository
{
    private const FIELDS = [
        'login_id', 'name', 'slug', 'selector_type', 'bank_account_iban', 'bank_account_number',
        'firefly_account_id', 'date_from', 'date_to', 'description_regex_match',
        'description_regex_replace', 'force_mt940', 'skip_transaction_review', 'schedule_cron', 'enabled',
    ];

    public function __construct(private readonly PDO $pdo)
    {
    }

    /** @return array<int, array<string, mixed>> */
    public function all(): array
    {
        return $this->pdo->query(
            'SELECT a.*, l.name AS login_name
               FROM accounts a
               JOIN logins l ON l.id = a.login_id
              ORDER BY a.name COLLATE NOCASE'
        )->fetchAll();
    }

    /** @return array<string, mixed>|null */
    public function find(int $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM accounts WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();

        return $row === false ? null : $row;
    }

    /** @return array<string, mixed>|null */
    public function findBySlug(string $slug): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM accounts WHERE slug = ?');
        $stmt->execute([$slug]);
        $row = $stmt->fetch();

        return $row === false ? null : $row;
    }

    /** @return array<int, array<string, mixed>> */
    public function byLogin(int $loginId): array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM accounts WHERE login_id = ? ORDER BY name COLLATE NOCASE');
        $stmt->execute([$loginId]);

        return $stmt->fetchAll();
    }

    /**
     * Accounts that are enabled and carry a schedule. The scheduler decides which of these are due.
     *
     * @return array<int, array<string, mixed>>
     */
    public function scheduled(): array
    {
        return $this->pdo->query(
            "SELECT * FROM accounts WHERE enabled = 1 AND schedule_cron <> '' ORDER BY id"
        )->fetchAll();
    }

    /** @param array<string, mixed> $data */
    public function create(array $data): int
    {
        $cols = self::FIELDS;
        $placeholders = implode(', ', array_map(static fn ($c) => ':' . $c, $cols));
        $stmt = $this->pdo->prepare(
            'INSERT INTO accounts (' . implode(', ', $cols) . ') VALUES (' . $placeholders . ')'
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
        $stmt = $this->pdo->prepare("UPDATE accounts SET $set, updated_at = datetime('now') WHERE id = :id");
        $stmt->execute($params);
    }

    public function delete(int $id): void
    {
        $stmt = $this->pdo->prepare('DELETE FROM accounts WHERE id = ?');
        $stmt->execute([$id]);
    }

    public function slugExists(string $slug, ?int $exceptId = null): bool
    {
        $sql = 'SELECT COUNT(*) FROM accounts WHERE slug = ?';
        $params = [$slug];
        if ($exceptId !== null) {
            $sql .= ' AND id <> ?';
            $params[] = $exceptId;
        }
        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($params);

        return (int) $stmt->fetchColumn() > 0;
    }

    /**
     * @param array<string, mixed> $data
     * @return array<string, mixed>
     */
    private function bind(array $data): array
    {
        $params = [];
        foreach (self::FIELDS as $field) {
            $value = $data[$field] ?? '';
            if (in_array($field, ['force_mt940', 'skip_transaction_review', 'enabled', 'login_id'], true)) {
                $value = (int) $value;
            }
            $params[$field] = $value;
        }

        return $params;
    }
}
