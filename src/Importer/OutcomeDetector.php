<?php

declare(strict_types=1);

namespace App\Importer;

/**
 * Classifies an importer response into an {@see Outcome}. The importer's headless mode historically
 * answers everything with HTTP 200 and HTML, so this is deliberately a chain that upgrades as the
 * importer gains a machine-readable status:
 *
 *   1. JSON body     — the importer patched to return `{status, transactions, ...}` (format=json).
 *   2. HTTP status   — the same patch also sets a real status code (409/404/422/500).
 *   3. HTML heuristic — the fallback for an unpatched importer. It classifies as success ONLY on a
 *      positively recognized "Import finished" page; anything else — a TAN prompt, an error page, a
 *      fatal error, an unrecognized page — is a failure, never a silent success.
 *
 * This ordering means a run is never reported as succeeding unless it demonstrably did.
 */
final class OutcomeDetector
{
    /** #239 status name => our Outcome status */
    private const JSON_STATUS_MAP = [
        'ok'                   => Outcome::SUCCESS,
        'tan_required'         => Outcome::TAN_REQUIRED,
        'tan_device_ambiguous' => Outcome::TAN_REQUIRED,
        'config_not_found'     => Outcome::FAILURE,
        'verification_failed'  => Outcome::FAILURE,
        'importer_error'       => Outcome::FAILURE,
        'stalled'              => Outcome::FAILURE,
    ];

    public function detect(int $httpStatus, string $body, string $contentType = ''): Outcome
    {
        return $this->fromJson($httpStatus, $body, $contentType)
            ?? $this->fromHttpStatus($httpStatus, $body)
            ?? $this->fromHtml($httpStatus, $body);
    }

    private function fromJson(int $httpStatus, string $body, string $contentType): ?Outcome
    {
        $looksJson = str_contains($contentType, 'json')
            || str_starts_with(ltrim($body), '{');
        if (!$looksJson) {
            return null;
        }
        $data = json_decode(trim($body), true);
        if (!is_array($data) || !isset($data['status']) || !is_string($data['status'])) {
            return null;
        }
        $status = self::JSON_STATUS_MAP[$data['status']] ?? Outcome::FAILURE;
        $num = isset($data['transactions']) && is_numeric($data['transactions'])
            ? (int) $data['transactions'] : null;
        $reason = $status === Outcome::SUCCESS
            ? 'Importer reported success.'
            : trim(($data['error_header'] ?? $data['status']) . ' ' . ($data['error_message'] ?? ''));

        return new Outcome($status, $reason ?: (string) $data['status'], $httpStatus, $num, 'json');
    }

    private function fromHttpStatus(int $httpStatus, string $body): ?Outcome
    {
        // Only trust a non-200 status code here; an unpatched importer always returns 200, which
        // tells us nothing, so we fall through to the HTML heuristic in that case.
        if ($httpStatus === 200) {
            return null;
        }

        return match ($httpStatus) {
            409 => new Outcome(Outcome::TAN_REQUIRED, 'A TAN is required before this run can complete.', $httpStatus, null, 'http'),
            404 => new Outcome(Outcome::FAILURE, 'The importer could not find the configuration.', $httpStatus, null, 'http'),
            422 => new Outcome(Outcome::FAILURE, 'The bank account or Firefly account could not be verified.', $httpStatus, null, 'http'),
            default => new Outcome(Outcome::FAILURE, "The importer returned HTTP $httpStatus.", $httpStatus, null, 'http'),
        };
    }

    private function fromHtml(int $httpStatus, string $body): Outcome
    {
        // A PHP fatal error can appear on any page; treat it as a failure first.
        if (stripos($body, 'Fatal error') !== false) {
            return new Outcome(Outcome::FAILURE, 'The importer hit a fatal error.', $httpStatus, null, 'html');
        }

        // Positively recognized success page (done.twig).
        if (str_contains($body, 'Import finished') || str_contains($body, 'transactions have been sent to Firefly III')) {
            $num = null;
            if (preg_match('/([0-9]+)\s+transactions have been sent/i', $body, $m) === 1) {
                $num = (int) $m[1];
            }

            return new Outcome(Outcome::SUCCESS, 'Import finished.', $httpStatus, $num, 'html');
        }

        // Interactive stalls: the headless run stopped and needs a human.
        if (str_contains($body, 'Enter TAN') || str_contains($body, 'requested a TAN')) {
            return new Outcome(Outcome::TAN_REQUIRED, 'The bank requested a TAN.', $httpStatus, null, 'html');
        }
        if (str_contains($body, 'Choose a device') || str_contains($body, 'choose-2fa-device')) {
            return new Outcome(Outcome::TAN_REQUIRED, 'The bank needs a TAN device to be chosen.', $httpStatus, null, 'html');
        }

        // Known error page (error.twig). Pull out the headline for context.
        if (preg_match('#<h1>(.*?)</h1>#si', $body, $m) === 1) {
            $header = trim(strip_tags($m[1]));
            if ($header !== '' && stripos($header, 'finished') === false) {
                return new Outcome(Outcome::FAILURE, $header, $httpStatus, null, 'html');
            }
        }

        // Anything not recognized as success is a failure by construction.
        return new Outcome(Outcome::FAILURE, 'Unrecognized importer response (no success marker).', $httpStatus, null, 'html');
    }
}
