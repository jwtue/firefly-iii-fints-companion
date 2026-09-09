<?php

declare(strict_types=1);

namespace App\Config;

/**
 * Writes the rendered importer configuration files into the directory the importer reads, one file
 * per account named `<slug>.json`. These files are generated artifacts owned by the sidecar; the
 * normalized model in the database is the source of truth.
 */
final class ConfigWriter
{
    public function __construct(private readonly string $configDir)
    {
    }

    public function write(string $slug, string $json): void
    {
        $this->ensureDir();
        $path = $this->pathFor($slug);
        // Write atomically so the importer never reads a half-written file mid-run.
        $tmp = $path . '.tmp';
        file_put_contents($tmp, $json, LOCK_EX);
        rename($tmp, $path);
    }

    public function delete(string $slug): void
    {
        $path = $this->pathFor($slug);
        if (is_file($path)) {
            unlink($path);
        }
    }

    public function exists(string $slug): bool
    {
        return is_file($this->pathFor($slug));
    }

    public function fileName(string $slug): string
    {
        return $slug . '.json';
    }

    private function pathFor(string $slug): string
    {
        // The slug is validated to contain no path separators; basename is a second line of defence.
        return rtrim($this->configDir, '/\\') . DIRECTORY_SEPARATOR . basename($slug) . '.json';
    }

    private function ensureDir(): void
    {
        if (!is_dir($this->configDir)) {
            mkdir($this->configDir, 0o770, true);
        }
    }
}
