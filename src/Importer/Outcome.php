<?php

declare(strict_types=1);

namespace App\Importer;

/**
 * The classified result of one importer run, independent of how it was detected (JSON status, HTTP
 * status code, or the HTML fallback heuristic).
 */
final class Outcome
{
    public const SUCCESS = 'success';
    public const FAILURE = 'failure';
    public const TAN_REQUIRED = 'tan_required';

    public function __construct(
        public readonly string $status,
        public readonly string $reason,
        public readonly ?int $httpStatus = null,
        public readonly ?int $numTransactions = null,
        public readonly string $source = '',
    ) {
    }

    public function isSuccess(): bool
    {
        return $this->status === self::SUCCESS;
    }

    public function needsTan(): bool
    {
        return $this->status === self::TAN_REQUIRED;
    }
}
