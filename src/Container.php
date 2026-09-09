<?php

declare(strict_types=1);

namespace App;

use App\Auth\Auth;
use App\Config\ConfigWriter;
use App\Importer\GuzzleTransport;
use App\Importer\ImporterClient;
use App\Importer\ImporterTransport;
use App\Notify\NullNotifier;
use App\Notify\Notifier;
use App\Notify\TelegramNotifier;
use App\Runner\Runner;
use App\Runner\RunnerInterface;
use App\Support\Database;
use App\Support\Lock;
use App\Support\Settings;
use DI\ContainerBuilder;
use PDO;
use Psr\Container\ContainerInterface;
use Slim\Views\Twig;

use function DI\autowire;
use function DI\factory;
use function DI\get;

/**
 * Builds the dependency-injection container. Everything the app and the scheduler need is wired here,
 * so both entrypoints (public/index.php and bin/scheduler.php) share one definition of the graph.
 */
final class Container
{
    public static function build(): ContainerInterface
    {
        $builder = new ContainerBuilder();
        $builder->addDefinitions([
            'config.database_path' => getenv('SIDECAR_DATABASE_PATH') ?: '/data/sidecar/sidecar.sqlite',
            'config.config_dir'    => getenv('SIDECAR_CONFIG_DIR') ?: '/data/configurations',
            'config.lock_file'     => getenv('SIDECAR_LOCK_FILE') ?: '/data/sidecar/run.lock',
            'config.templates_dir' => dirname(__DIR__) . '/templates',

            Database::class => factory(static fn (ContainerInterface $c) => new Database($c->get('config.database_path'))),
            PDO::class      => factory(static fn (ContainerInterface $c) => $c->get(Database::class)->pdo()),
            Settings::class => autowire(),

            ImporterTransport::class => factory(static fn () => new GuzzleTransport()),
            ImporterClient::class    => factory(static function (ContainerInterface $c) {
                return new ImporterClient($c->get(ImporterTransport::class), $c->get(Settings::class)->get('importer_url'));
            }),

            ConfigWriter::class => factory(static fn (ContainerInterface $c) => new ConfigWriter($c->get('config.config_dir'))),
            Lock::class         => factory(static fn (ContainerInterface $c) => new Lock($c->get('config.lock_file'))),
            RunnerInterface::class => get(Runner::class),
            Auth::class         => factory(static fn () => new Auth(Auth::configuredHash())),

            Notifier::class => factory(static function (ContainerInterface $c) {
                $settings = $c->get(Settings::class);
                $token = $settings->get('telegram_bot_token');
                $chat = $settings->get('telegram_chat_id');
                if ($token !== '' && $chat !== '') {
                    return new TelegramNotifier($c->get(ImporterTransport::class), $token, $chat);
                }

                return new NullNotifier();
            }),

            Twig::class => factory(static function (ContainerInterface $c) {
                return Twig::create($c->get('config.templates_dir'), [
                    'cache' => false,
                    'autoescape' => 'html',
                ]);
            }),
        ]);

        return $builder->build();
    }
}
