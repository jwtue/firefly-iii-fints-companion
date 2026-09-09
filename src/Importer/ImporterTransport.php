<?php

declare(strict_types=1);

namespace App\Importer;

/**
 * The HTTP call to the importer, behind an interface so the runner and its tests do not depend on a
 * real network. Implementations must not throw on HTTP error responses — a 4xx/5xx is a valid
 * outcome to classify, not an exception.
 *
 * @phpstan-type Response array{status:int, body:string, contentType:string}
 */
interface ImporterTransport
{
    /**
     * @return array{status:int, body:string, contentType:string}
     */
    public function get(string $url): array;
}
