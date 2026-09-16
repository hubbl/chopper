import ast
from pathlib import Path
from string import Formatter

import pytest

from chopper import i18n
from chopper.app import MainWindow
from chopper.detectors import REGISTRY


def test_catalogs_have_matching_keys_and_placeholders():
    english = i18n.load_catalog("en")
    german = i18n.load_catalog("de")
    assert english.keys() == german.keys()
    formatter = Formatter()

    def fields(text):
        return {
            (name, spec, conversion)
            for _, name, spec, conversion in formatter.parse(text)
            if name is not None
        }

    for key in english:
        assert english[key] and german[key]
        assert fields(english[key]) == fields(german[key]), key


def test_all_static_translation_keys_exist():
    catalog = i18n.load_catalog("en")
    for path in Path(i18n.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                assert node.args[0].value in catalog, (path, node.lineno)
    for spec in REGISTRY.values():
        assert spec.name in catalog
        for parameter in spec.parameters:
            assert parameter.label in catalog
            assert not parameter.suffix or parameter.suffix in catalog


@pytest.mark.parametrize(
    ("requested", "expected"),
    [("en", "en"), ("de-DE", "de"), ("de_DE", "de"), ("fr", "en"), ("../de", "en")],
)
def test_language_resolution(requested, expected):
    assert i18n.resolve_language(requested) == expected


def test_translation_and_english_fallback(monkeypatch):
    monkeypatch.setattr(i18n, "LANGUAGE", "de")
    assert i18n.tr("action.undo") == "Rückgängig"
    assert i18n.tr("selection.counts", markers=1, segments=2) == "Marker: 1  ·  Segmente: 2"
    monkeypatch.delitem(i18n.load_catalog("de"), "action.undo")
    assert i18n.tr("action.undo") == "Undo"
    assert i18n.tr("External detector") == "External detector"


@pytest.mark.parametrize(
    ("language", "open_text", "parameter_text"),
    [("en", "Open WAV …", "Peak threshold"), ("de", "WAV öffnen …", "Peak-Schwelle")],
)
def test_window_uses_selected_language(app, monkeypatch, language, open_text, parameter_text):
    monkeypatch.setattr(i18n, "LANGUAGE", language)
    window = MainWindow()
    try:
        assert window.open_button.text() == open_text
        assert (
            window.parameter_form.labelForField(window.parameter_widgets["threshold_db"]).text()
            == parameter_text
        )
    finally:
        window.close()
