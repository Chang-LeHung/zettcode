"""The models a config file holds: list them, add one, change one, remove one.

An editor that hosts ZettCode has to be able to set a model up before there is any client: a fresh machine has no
``~/.zettcode/config.toml``, and a client cannot be made without a model. These functions work on the file itself, so
they answer with no client, no provider, and no network — the terminal's ``/config`` edits the same file with the same
helpers, so a model added here reads there, and the other way round.

Nothing is believed until it is read back: the new file is parsed and every entry validated before the call returns,
and a write that would not parse is undone.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .. import config as _config
from ..config_edit import entry_from_model, render_entry, replace_model, write_text_atomically
from ..paths import config_path
from .types import ModelInfo

__all__ = ["add_model", "list_models", "remove_model", "update_model"]


def _infos(models: tuple[_config.ModelConfig, ...]) -> tuple[ModelInfo, ...]:
    """Return the configured models as SDK values; none is marked active, which only a client knows."""
    return tuple(
        ModelInfo(
            name=model.shown_name,
            model=model.model,
            context_window=model.context_window,
            multimodal=model.multimodal,
            efforts=tuple(level.value for level in model.efforts),
            compact_percent=model.compact_percent,
            web_search=model.web_search,
            web_search_name=model.web_search_name,
            display_model=model.display_model,
            base_url=model.base_url,
            api=model.api.value,
            temperature=model.temperature,
        )
        for model in models
    )


def _path(path: str | Path | None) -> Path:
    """Return the config file an edit goes to."""
    return config_path(path)


def _read_text(target: Path) -> str:
    """Return the file's text, or nothing when it does not exist yet."""
    return target.read_text(encoding="utf-8") if target.is_file() else ""


def _write(target: Path, before: str | None, text: str) -> tuple[_config.ModelConfig, ...]:
    """Write ``text``, read it back, and undo the write when what came back cannot be used."""
    target.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomically(target, text)
    try:
        return _config.read_models(target)
    except ValueError:
        if before is None:
            target.unlink(missing_ok=True)
        else:
            write_text_atomically(target, before)
        raise


def list_models(path: str | Path | None = None) -> tuple[ModelInfo, ...]:
    """Return the models the config file lists, or nothing when it lists none.

    Raises:
        ValueError: The file does not parse, or an entry is not usable as one.
    """
    return _infos(_config.read_models(_path(path)))


def add_model(entry: Mapping[str, object], *, path: str | Path | None = None) -> tuple[ModelInfo, ...]:
    """Add one model to the config file and return every model it now lists.

    The entry uses the file's own keys — ``model``, ``token``, and optionally ``display_model``, ``base_url``,
    ``anthropic``, ``responses_api``, ``multimodal``, ``web_search``, ``web_search_name``, ``context_window``,
    ``compact_percent``,
    ``reasoning_efforts`` — and is validated by reading the file back before returning. The first model is written
    by hand (the file has no block to insert after); later ones go through the same editor the terminal's ``/config``
    uses, so the rest of the file, comments included, is left as it was.

    Raises:
        ValueError: The entry is not a usable model, or the file would not parse.
    """
    target = _path(path)
    before = target.read_text(encoding="utf-8") if target.is_file() else None
    existing = _config.read_models(target) if target.is_file() else ()
    text = before or ""
    if existing:
        from ..config_edit import add_model as insert_model

        text = insert_model(text, entry, where=target)
    else:
        block = render_entry(entry).rstrip("\n")
        text = f"{text.rstrip()}\n\n{block}\n" if text.strip() else f"{block}\n"
    return _infos(_write(target, before, text))


def _find(models: tuple[_config.ModelConfig, ...], name: str) -> int:
    """Return the place of the model called ``name`` (its display name, or its id)."""
    for index, model in enumerate(models):
        if name in (model.shown_name, model.model):
            return index
    raise ValueError(f"No model called {name!r}; configured: {', '.join(model.shown_name for model in models)}")


def update_model(name: str, changes: Mapping[str, object], *, path: str | Path | None = None) -> tuple[ModelInfo, ...]:
    """Change the model called ``name``, leaving every key not named as it is, and return the new list.

    ``changes`` holds the file's keys. The token is kept unless a new one is given, so a window or a display name can
    be changed without repeating a secret. A key whose value is ``None`` is removed from the entry, which is how a
    temperature is cleared and how one protocol flag gives way to another without being left behind as ``false``.

    Raises:
        ValueError: No model is called ``name``, or the result is not usable.
    """
    target = _path(path)
    models = _config.read_models(target)
    index = _find(models, name)
    entry = entry_from_model(models[index])
    for key, value in changes.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    before = _read_text(target)
    text = replace_model(before, index, entry, where=target)
    return _infos(_write(target, before, text))


def remove_model(name: str, *, path: str | Path | None = None) -> tuple[ModelInfo, ...]:
    """Remove the model called ``name`` and return the rest.

    Raises:
        ValueError: No model is called ``name``, or it is the last one: a configuration with no models is one no
            client can be made from, so another has to be added first.
    """
    from ..config_edit import remove_model as drop_model

    target = _path(path)
    models = _config.read_models(target)
    index = _find(models, name)
    before = _read_text(target)
    text = drop_model(before, index, where=target)
    return _infos(_write(target, before, text))
