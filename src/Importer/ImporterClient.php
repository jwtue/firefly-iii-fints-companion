<?php

declare(strict_types=1);

namespace App\Importer;

/**
 * Builds the importer's headless trigger URL and performs the call. `format=json` is always
 * requested: a patched importer answers with a machine-readable status, an unpatched one ignores the
 * unknown parameter and still returns its HTML, which the {@see OutcomeDetector} handles.
 */
final class ImporterClient
{
    public function __construct(
        private readonly ImporterTransport $transport,
        private readonly string $baseUrl,
    ) {
    }

    /**
     * @return array{status:int, body:string, contentType:string}
     */
    public function run(string $fileName): array
    {
        return $this->transport->get($this->urlFor($fileName));
    }

    public function urlFor(string $fileName): string
    {
        return rtrim($this->baseUrl, '/')
            . '/?automate=true&format=json&config=' . rawurlencode($fileName);
    }

    public function baseUrl(): string
    {
        return $this->baseUrl;
    }
}
