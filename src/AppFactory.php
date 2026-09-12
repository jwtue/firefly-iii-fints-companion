<?php

declare(strict_types=1);

namespace App;

use App\Auth\AuthMiddleware;
use App\Config\Schedule;
use App\Http\AccountsController;
use App\Http\AuthController;
use App\Http\CsrfMiddleware;
use App\Http\DashboardController;
use App\Http\HealthController;
use App\Http\ImportController;
use App\Http\LangController;
use App\Http\LocaleMiddleware;
use App\Http\LoginsController;
use App\Http\RunsController;
use App\Http\SettingsController;
use App\Support\Csrf;
use App\Support\Flash;
use App\Support\Translator;
use Psr\Container\ContainerInterface;
use Slim\App;
use Slim\Factory\AppFactory as SlimAppFactory;
use Slim\Views\Twig;
use Slim\Views\TwigMiddleware;
use Twig\TwigFunction;

/** Builds the Slim application: Twig helpers, middleware stack and routes. */
final class AppFactory
{
    public static function create(ContainerInterface $container): App
    {
        SlimAppFactory::setContainer($container);
        $app = SlimAppFactory::create();

        /** @var Twig $twig */
        $twig = $container->get(Twig::class);
        $env = $twig->getEnvironment();
        $env->addFunction(new TwigFunction('csrf_token', static fn (): string => Csrf::token()));
        $env->addFunction(new TwigFunction('flash', static fn (): array => Flash::pull()));
        $env->addFunction(new TwigFunction('current_path', static function (): string {
            return (string) parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
        }));

        /** @var Translator $translator */
        $translator = $container->get(Translator::class);
        $env->addFunction(new TwigFunction('t', static fn (string $key, array $params = []): string => $translator->t($key, $params)));
        $env->addFunction(new TwigFunction('locale', static fn (): string => $translator->locale()));
        $env->addFunction(new TwigFunction('lang_available', static fn (): array => $translator->available()));
        // Human-readable schedule label from a cron string (e.g. "Daily 06:30"), for the lists.
        $env->addFunction(new TwigFunction('schedule_label', static function (string $cron) use ($translator): string {
            $s = Schedule::fromCron($cron);
            $wd = ['0' => 'wd_sun', '1' => 'wd_mon', '2' => 'wd_tue', '3' => 'wd_wed', '4' => 'wd_thu', '5' => 'wd_fri', '6' => 'wd_sat'];

            return match ($s['freq']) {
                'hourly' => $translator->t('accountform.freq_hourly'),
                'daily' => $translator->t('accountform.freq_daily') . ' ' . $s['time'],
                'weekly' => $translator->t('accountform.freq_weekly') . ' '
                    . $translator->t('accountform.' . ($wd[$s['weekday']] ?? 'wd_mon')) . ' ' . $s['time'],
                'custom' => $translator->t('accountform.freq_custom') . ': ' . $cron,
                default => $translator->t('common.manual'),
            };
        }));

        self::routes($app);

        // Middleware. Execution is the reverse of registration, so body parsing runs before the CSRF
        // check, authentication before the controllers, and locale resolution closest to the handler.
        $app->add($container->get(LocaleMiddleware::class));
        $app->add(new CsrfMiddleware());
        $app->add($container->get(AuthMiddleware::class));
        $app->add(TwigMiddleware::create($app, $twig));
        $app->addBodyParsingMiddleware();
        $app->addRoutingMiddleware();

        $debug = filter_var(getenv('SIDECAR_DEBUG') ?: 'false', FILTER_VALIDATE_BOOLEAN);
        $app->addErrorMiddleware($debug, true, true);

        return $app;
    }

    private static function routes(App $app): void
    {
        $app->get('/healthz', [HealthController::class, 'index']);
        $app->get('/lang/{locale}', [LangController::class, 'switch']);

        $app->get('/login', [AuthController::class, 'showLogin']);
        $app->post('/login', [AuthController::class, 'login']);
        $app->post('/logout', [AuthController::class, 'logout']);

        $app->get('/', [DashboardController::class, 'index']);

        $app->get('/logins', [LoginsController::class, 'index']);
        $app->get('/logins/new', [LoginsController::class, 'create']);
        $app->post('/logins', [LoginsController::class, 'store']);
        $app->get('/logins/{id}/edit', [LoginsController::class, 'edit']);
        $app->post('/logins/{id}', [LoginsController::class, 'update']);
        $app->post('/logins/{id}/delete', [LoginsController::class, 'delete']);
        $app->get('/logins/{id}/reauth', [LoginsController::class, 'reauthForm']);
        $app->post('/logins/{id}/reauth', [LoginsController::class, 'reauth']);

        $app->get('/accounts', [AccountsController::class, 'index']);
        $app->get('/accounts/new', [AccountsController::class, 'create']);
        $app->post('/accounts', [AccountsController::class, 'store']);
        $app->get('/accounts/{id}/edit', [AccountsController::class, 'edit']);
        $app->post('/accounts/{id}', [AccountsController::class, 'update']);
        $app->post('/accounts/{id}/delete', [AccountsController::class, 'delete']);
        $app->post('/accounts/{id}/duplicate', [AccountsController::class, 'duplicate']);
        $app->post('/accounts/{id}/run', [AccountsController::class, 'run']);

        $app->get('/runs', [RunsController::class, 'index']);
        $app->get('/runs/{id}', [RunsController::class, 'show']);

        $app->get('/import', [ImportController::class, 'index']);
        $app->post('/import', [ImportController::class, 'apply']);

        $app->get('/settings', [SettingsController::class, 'edit']);
        $app->post('/settings', [SettingsController::class, 'update']);
        $app->post('/settings/test', [SettingsController::class, 'testTelegram']);
    }
}
