<?php

declare(strict_types=1);

namespace App\Model;

use PDO;

/**
 * The run history: one row per import attempt, with its outcome and a redacted excerpt of the
 * importer's response. This is the observability the importer itself does not provide.
 */
final class RunRepository
{
    public function __construct(private readonly PDO $pdo)
    {
    }

    public function start(int $accountId, string $accountName, ?int $loginId, string $trigger): int
    {
        $stmt = $this->pdo->prepare(
            "INSERT INTO runs (account_id, account_name, login_id, trigger, status)
             VALUES (?, ?, ?, ?, 'running')"
        );
        $stmt->execute([$accountId, $accountName, $loginId, $trigger]);

        return (int) $this->pdo->lastInsertId();
    }

    public function finish(
        int $runId,
        string $status,
        string $reason,
        ?int $httpStatus,
        string $responseExcerpt,
        ?int $numTransactions,
        int $durationMs
    ): void {
        $stmt = $this->pdo->prepare(
            "UPDATE runs
                SET status = :status,
                    outcome_reason = :reason,
                    http_status = :http,
                    response_excerpt = :excerpt,
                    num_transactions = :num,
                    finished_at = datetime('now'),
                    duration_ms = :duration
              WHERE id = :id"
        );
        $stmt->execute([
            'status' => $status,
            'reason' => $reason,
            'http' => $httpStatus,
            'excerpt' => $responseExcerpt,
            'num' => $numTransactions,
            'duration' => $durationMs,
            'id' => $runId,
        ]);
    }

    /** @return array<int, array<string, mixed>> */
    public function recent(int $limit = 100): array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM runs ORDER BY id DESC LIMIT ?');
        $stmt->bindValue(1, $limit, PDO::PARAM_INT);
        $stmt->execute();

        return $stmt->fetchAll();
    }

    /** @return array<string, mixed>|null */
    public function find(int $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM runs WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();

        return $row === false ? null : $row;
    }

    /** @return array<string, mixed>|null the most recent finished run for an account */
    public function lastForAccount(int $accountId): ?array
    {
        $stmt = $this->pdo->prepare(
            "SELECT * FROM runs WHERE account_id = ? AND status <> 'running' ORDER BY id DESC LIMIT 1"
        );
        $stmt->execute([$accountId]);
        $row = $stmt->fetch();

        return $row === false ? null : $row;
    }
}
