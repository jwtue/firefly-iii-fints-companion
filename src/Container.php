<?php

declare(strict_types=1);

namespace App;

use App\Auth\Auth;
use App\Auth\AuthMiddleware;
use App\Config\ConfigImporter;
use App\Config\ConfigWriter;
use App\Model\LoginRepository;
use App\Support\Cidr;
use App\Importer\GuzzleTransport;
use App\Importer\ImporterClient;
use App\Importer\ImporterTransport;
use App\Model\AccountRepository;
use App\Model\RunRepository;
use App\Notify\NullNotifier;
use App\Notify\Notifier;
use App\Notify\TelegramNotifier;
use App\Runner\Runner;
use App\Runner\RunnerInterface;
use App\Scheduler\DeadMansSwitch;
use App\Support\Database;
use App\Support\Lock;
use App\Support\Settings;
use App\Support\Translator;
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
            'config.lang_dir'      => dirname(__DIR__) . '/lang',

            Translator::class => factory(static fn (ContainerInterface $c) => new Translator($c->get('config.lang_dir'))),

            Database::class => factory(static fn (ContainerInterface $c) => new Database($c->get('config.database_path'))),
            PDO::class      => factory(static fn (ContainerInterface $c) => $c->get(Database::class)->pdo()),
            Settings::class => autowire(),

            ImporterTransport::class => factory(static fn () => new GuzzleTransport()),
            ImporterClient::class    => factory(static function (ContainerInterface $c) {
                return new ImporterClient($c->get(ImporterTransport::class), $c->get(Settings::class)->get('importer_url'));
            }),

            ConfigWriter::class => factory(static fn (ContainerInterface $c) => new ConfigWriter($c->get('config.config_dir'))),
            ConfigImporter::class => factory(static fn (ContainerInterface $c) => new ConfigImporter(
                $c->get('config.config_dir'),
                $c->get(LoginRepository::class),
                $c->get(AccountRepository::class),
                $c->get(Settings::class),
            )),
            Lock::class         => factory(static fn (ContainerInterface $c) => new Lock($c->get('config.lock_file'))),
            RunnerInterface::class => get(Runner::class),
            DeadMansSwitch::class => factory(static fn (ContainerInterface $c) => new DeadMansSwitch(
                $c->get(PDO::class),
                $c->get(AccountRepository::class),
                $c->get(RunRepository::class),
                $c->get(Notifier::class),
                (int) (getenv('SIDECAR_DEADMAN_GRACE_MINUTES') ?: 60),
                (int) (getenv('SIDECAR_DEADMAN_REPEAT_HOURS') ?: 24),
            )),
            Auth::class         => factory(static fn () => new Auth(Auth::configuredHash())),
            AuthMiddleware::class => factory(static fn (ContainerInterface $c) => new AuthMiddleware(
                $c->get(Auth::class),
                Cidr::parseList(getenv('SIDECAR_TRUSTED_NETWORKS') ?: '')
            )),

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
