"""JSON message catalogs, selected once at startup (English by default)."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from importlib.resources import files

DEFAULT_LANGUAGE = "en"


@lru_cache
def load_catalog(language: str) -> dict[str, str]:
    """Load a packaged catalog. Only simple language codes are accepted."""
    if not language.isascii() or not language.isalpha():
        raise ValueError(f"Invalid language code: {language!r}")
    data = json.loads(files("chopper").joinpath("locales", f"{language}.json").read_text("utf-8"))
    if not isinstance(data, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in data.items()
    ):
        raise ValueError(f"Invalid translation catalog: {language}")
    return data


def resolve_language(language: str) -> str:
    """Use the base language for regional codes and English for unknown languages."""
    code = language.strip().lower().replace("_", "-").split("-")[0]
    try:
        load_catalog(code)
    except (FileNotFoundError, ValueError):
        return DEFAULT_LANGUAGE
    return code


LANGUAGE = resolve_language(os.environ.get("CHOPPER_LANGUAGE", DEFAULT_LANGUAGE))


def tr(key: str, **values: object) -> str:
    """Translate a key and interpolate named values, with English fallback.

    Unknown keys remain readable, allowing external detectors to supply literal
    labels. Catalogs are cached, so audio callbacks never perform file I/O.
    """
    template = load_catalog(LANGUAGE).get(key, load_catalog(DEFAULT_LANGUAGE).get(key, key))
    return template.format(**values) if values else template
