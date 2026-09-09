<?php

declare(strict_types=1);

namespace App\Auth;

/**
 * Single-user password authentication. The password is configured out of band as either a bcrypt
 * hash (SIDECAR_PASSWORD_HASH, preferred) or, for convenience, a plaintext password (SIDECAR_PASSWORD)
 * that is hashed once at startup. The UI edits bank secrets, so the application refuses to start
 * without one of these (enforced in the entrypoint).
 */
final class Auth
{
    public function __construct(private readonly string $passwordHash)
    {
    }

    /** Resolve the configured bcrypt hash from the environment, or '' if none is set. */
    public static function configuredHash(): string
    {
        $hash = getenv('SIDECAR_PASSWORD_HASH');
        if (is_string($hash) && $hash !== '') {
            return $hash;
        }
        $plain = getenv('SIDECAR_PASSWORD');
        if (is_string($plain) && $plain !== '') {
            return password_hash($plain, PASSWORD_DEFAULT);
        }

        return '';
    }

    public function attempt(string $password): bool
    {
        if ($this->passwordHash === '' || !password_verify($password, $this->passwordHash)) {
            return false;
        }
        $_SESSION['authenticated'] = true;
        // Defend against session fixation on privilege change.
        session_regenerate_id(true);
        $_SESSION['authenticated'] = true;

        return true;
    }

    public function isAuthenticated(): bool
    {
        return isset($_SESSION['authenticated']) && $_SESSION['authenticated'] === true;
    }

    public function logout(): void
    {
        $_SESSION = [];
        session_destroy();
    }
}
