<?php

declare(strict_types=1);

namespace App\Runner;

use RuntimeException;

/** Thrown when another import is already running and the requested one cannot start right now. */
final class RunnerBusyException extends RuntimeException
{
}
