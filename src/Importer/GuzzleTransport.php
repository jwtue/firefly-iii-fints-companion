<?php

declare(strict_types=1);

namespace App\Importer;

use GuzzleHttp\Client;
use GuzzleHttp\Exception\GuzzleException;

/**
 * The real transport: a Guzzle client that never throws on HTTP status (http_errors = false), so a
 * 4xx/5xx from the importer reaches the detector as a classifiable response. A transport-level
 * failure (connection refused, timeout) is turned into a synthetic 0-status response with the error
 * text as body, so it is recorded as a failed run rather than crashing the runner.
 */
final class GuzzleTransport implements ImporterTransport
{
    private Client $client;

    public function __construct(int $timeoutSeconds = 600)
    {
        $this->client = new Client([
            'http_errors'     => false,
            'timeout'         => $timeoutSeconds,
            'connect_timeout' => 10,
            'allow_redirects' => false,
        ]);
    }

    public function get(string $url): array
    {
        try {
            $response = $this->client->get($url);

            return [
                'status'      => $response->getStatusCode(),
                'body'        => (string) $response->getBody(),
                'contentType' => $response->getHeaderLine('Content-Type'),
            ];
        } catch (GuzzleException $e) {
            return [
                'status'      => 0,
                'body'        => 'Transport error contacting the importer: ' . $e->getMessage(),
                'contentType' => 'text/plain',
            ];
        }
    }
}
