<?php

declare(strict_types=1);

namespace App\Support;

/**
 * A cross-process advisory lock (flock on a shared file) that serializes importer runs, so a manual
 * "run now" and the scheduler can never hit the same bank at the same time. The lock file lives on
 * the shared data volume, so it works across the web and scheduler containers.
 */
final class Lock
{
    /** @var resource|null */
    private $handle = null;

    public function __construct(private readonly string $file)
    {
    }

    public function tryAcquire(): bool
    {
        $dir = dirname($this->file);
        if (!is_dir($dir)) {
            mkdir($dir, 0o770, true);
        }
        $handle = fopen($this->file, 'c');
        if ($handle === false) {
            return false;
        }
        if (!flock($handle, LOCK_EX | LOCK_NB)) {
            fclose($handle);

            return false;
        }
        $this->handle = $handle;

        return true;
    }

    public function release(): void
    {
        if ($this->handle !== null) {
            flock($this->handle, LOCK_UN);
            fclose($this->handle);
            $this->handle = null;
        }
    }
}
