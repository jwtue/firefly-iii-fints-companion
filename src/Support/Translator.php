<?php

declare(strict_types=1);

namespace App\Support;

/**
 * Minimal message translator for the bilingual (English/German) UI. Catalogs are plain PHP arrays in
 * lang/<locale>.php. Templates call `t('key')`; flash messages and validation errors are stored as
 * keys and translated at render time, so controllers stay language-agnostic. Unknown keys fall back
 * to English and then to the key itself, so a missing translation degrades gracefully.
 */
final class Translator
{
    private const AVAILABLE = ['en', 'de'];
    private const DEFAULT = 'en';

    private string $locale = self::DEFAULT;
    /** @var array<string, array<string, string>> */
    private array $messages = [];

    public function __construct(string $langDir)
    {
        foreach (self::AVAILABLE as $locale) {
            $file = rtrim($langDir, '/\\') . DIRECTORY_SEPARATOR . $locale . '.php';
            $this->messages[$locale] = is_file($file) ? (array) require $file : [];
        }
    }

    public function setLocale(string $locale): void
    {
        if (in_array($locale, self::AVAILABLE, true)) {
            $this->locale = $locale;
        }
    }

    public function locale(): string
    {
        return $this->locale;
    }

    /** @return string[] */
    public function available(): array
    {
        return self::AVAILABLE;
    }

    /**
     * Resolve the locale from a cookie value, then an Accept-Language header, then the default.
     */
    public function resolve(?string $cookie, string $acceptLanguage): string
    {
        if ($cookie !== null && in_array($cookie, self::AVAILABLE, true)) {
            return $cookie;
        }
        foreach (explode(',', strtolower($acceptLanguage)) as $part) {
            $tag = trim(explode(';', $part)[0]);
            $primary = substr($tag, 0, 2);
            if (in_array($primary, self::AVAILABLE, true)) {
                return $primary;
            }
        }

        return self::DEFAULT;
    }

    /** @param array<string, string|int> $params */
    public function t(string $key, array $params = []): string
    {
        $text = $this->messages[$this->locale][$key]
            ?? $this->messages[self::DEFAULT][$key]
            ?? $key;
        foreach ($params as $name => $value) {
            $text = str_replace('{' . $name . '}', (string) $value, $text);
        }

        return $text;
    }
}
