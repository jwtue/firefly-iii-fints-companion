<?php

declare(strict_types=1);

use App\AppFactory;
use App\Auth\Auth;
use App\Container;
use Dotenv\Dotenv;

require __DIR__ . '/../vendor/autoload.php';

// Load a .env file if present (development); in production the environment is passed by the container.
if (is_file(__DIR__ . '/../.env')) {
    Dotenv::createImmutable(dirname(__DIR__))->safeLoad();
}

// The UI edits bank secrets, so refuse to start unless access is protected somehow: a password, or
// a trusted-network bypass. Fail closed if neither is configured.
$trustedNetworks = trim((string) (getenv('SIDECAR_TRUSTED_NETWORKS') ?: ''));
if (Auth::configuredHash() === '' && $trustedNetworks === '') {
    http_response_code(500);
    header('Content-Type: text/plain');
    echo "Refusing to start: set SIDECAR_PASSWORD (or SIDECAR_PASSWORD_HASH), or SIDECAR_TRUSTED_NETWORKS, to protect the UI.\n";
    exit(1);
}

$behindTls = filter_var(getenv('SIDECAR_BEHIND_TLS') ?: 'true', FILTER_VALIDATE_BOOLEAN);
session_set_cookie_params([
    'httponly' => true,
    'samesite' => 'Lax',
    'secure' => $behindTls,
]);
session_start();

$container = Container::build();
$app = AppFactory::create($container);
$app->run();
