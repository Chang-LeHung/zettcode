"""``/config``: add, change and remove the models in the config file from inside the shell.

The pages are the shell's usual ones — a list to choose from, a line to answer — stacked one after
another; this module is the order they come in. Each step replaces the page before it, Escape on any
step abandons the whole thing, and nothing is written until the last answer is in. What is written is
decided by :mod:`.config_form` and :mod:`zettcode.config_edit`; what this module adds is only the
sequence and the sentence the reader is left with.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from ...config_edit import ConfigEditError
from ...providers import API_FLAG_KEYS, CUSTOM, Api
from ...tui import SEPARATOR, ListItem, ListPage, Screen, Widget
from ..agent.conversation.rows import compact_path
from .config_form import (
    Draft,
    describe,
    entry_for,
    limits_text,
    parse_add,
    parse_percent,
    parse_tokens,
    tokens_text,
    whole_if_whole,
)
from .shell import PAGE_SCREEN, ShellState
from .widgets import INPUT_ROWS, InputPage, bottom_panel

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from ...config import ModelConfig
    from ...providers import Provider

#: Rows the list pages take: the title, a blank, up to eight rows, the keys.
LIST_ROWS = 13

#: Rows the list of things to do with one model takes: ten of them.
ACTION_ROWS = 15

#: Columns the file's path may take under the title; a longer one keeps its end, where the name is.
SUBTITLE_COLUMNS = 70


class ConfigMixin(ShellState):
    """Walk the reader through changing the models, and apply the result to the running session."""

    # -- showing a page ------------------------------------------------------------------
    def _config_show(self, page: Widget, *, rows: int, replace: bool) -> None:
        """Put one step of the flow on screen, in place of the one before it when there is one."""
        if replace:
            self.app.pop_screen()
        self.app.push_screen(Screen(bottom_panel(page, rows=rows), name=PAGE_SCREEN, modal=True))
        self.app.request_layout()

    def _config_end(self, message: str | None = None, *, error: bool = False) -> None:
        """Close the flow and say how it ended."""
        self.close_page()
        if message:
            (self.transcript.error if error else self.transcript.notice)(message)
        self.app.invalidate()

    def _config_failed(self, error: Exception) -> None:
        """Close the flow on a refusal; the file was not touched."""
        self._config_end(f"/config: {error}", error=True)

    # -- the first page ------------------------------------------------------------------
    def config_page(self) -> Widget:
        """Return the models in the file, and a row to add another.

        The list is read from the file rather than from the session: it is what an edit will act
        on, and a reader who changed the file by hand since the start sees that here.
        """
        entries = self.agent.file_models()
        current = self.agent.active_model
        digits = len(str(len(entries)))
        rows = [
            ListItem(
                index,
                f"{index + 1:>{digits}}. {model.shown_name}{' (current)' if model == current else ''}",
                f"{model.model} {SEPARATOR} {model.api} {SEPARATOR} {model.base_url or 'default address'}",
            )
            for index, (model, _) in enumerate(entries)
        ]
        rows.append(ListItem(None, "+ Add a model", "from a provider, or any endpoint"))
        page = ListPage(
            rows,
            title="Models",
            subtitle=compact_path(self.agent.config_file, limit=SUBTITLE_COLUMNS),
            on_select=self._config_chosen,
            on_cancel=self.close_page,
        )
        return bottom_panel(page, rows=LIST_ROWS)

    def _config_chosen(self, item: ListItem) -> None:
        """A row of the model list: a model to change, or the row that adds one."""
        if item.value is None:
            self._config_pick_provider(replace=True)
        else:
            self._config_actions(int(item.value), replace=True)  # type: ignore[call-overload]

    # -- adding --------------------------------------------------------------------------
    def _config_pick_provider(self, *, replace: bool) -> None:
        """Ask which host the model is at."""
        rows = [
            ListItem(provider, provider.label, provider.note or provider.api.description)
            for provider in self.agent.providers
        ]
        rows.append(ListItem(CUSTOM, "Custom", "any endpoint; you give the address and the protocol"))
        page = ListPage(
            rows,
            title="Add a model \u2014 which provider?",
            on_select=lambda item: self._config_begin(None if item.value == CUSTOM else cast("Provider", item.value)),
            on_cancel=self._config_back,
        )
        self._config_show(page, rows=LIST_ROWS, replace=replace)

    def _config_back(self) -> None:
        """Go back to the model list."""
        try:
            page = self.config_page()
        except ConfigEditError as error:
            self._config_failed(error)
            return
        self.app.pop_screen()
        self.app.push_screen(Screen(page, name=PAGE_SCREEN, modal=True))
        self.app.request_layout()

    def _config_begin(self, provider: Provider | None) -> None:
        """Start asking what the provider does not already say."""
        draft = Draft.for_provider(provider)
        draft.from_panel = True
        self._config_ask(draft)

    def _config_step_back(self, draft: Draft) -> None:
        """Escape in a question: take back the last answer and ask it again, as it was answered.

        From the first question it goes to the provider list when the flow came from there, and
        closes when it was started from a typed line, which has nothing behind it.
        """
        previous = draft.undo()
        if previous is not None:
            self._config_ask(draft, initial=previous)
        elif draft.from_panel:
            self._config_pick_provider(replace=True)
        else:
            self._config_end()

    def _config_ask(self, draft: Draft, *, replace: bool = True, initial: str = "") -> None:
        """Ask for the next thing a draft is missing, or write it when nothing is.

        Args:
            draft: What is known so far.
            replace: Whether a page of this flow is on screen to be replaced. The first question
                of ``/config add`` typed with something left out has none.
            initial: What to put in the line, for a question being shown again after Escape.
        """
        wanted = draft.missing()
        if not wanted:
            self._config_write(draft)
            return
        step = wanted[0]
        host = draft.provider.label if draft.provider is not None else "a custom endpoint"
        if step == "api":
            self._config_ask_api(draft, replace=replace)
        elif step == "url":
            self._config_ask_text(
                f"Address of {host}",
                draft,
                lambda text: self._config_set(draft, "url", text),
                help_lines=(
                    "The address the client appends its route to.",
                    "For example: https://api.example.com/v1",
                ),
                allow_empty=not draft.custom,
                initial=initial,
                replace=replace,
            )
        elif step == "model":
            suggestions = draft.provider.models if draft.provider is not None else ()
            self._config_ask_text(
                f"Model id at {host}",
                draft,
                lambda text: self._config_set(draft, "model", text),
                help_lines=(
                    "The id the provider calls the model, exactly as its documentation writes it.",
                    *((f"For example: {', '.join(suggestions[:3])}",) if suggestions else ()),
                ),
                initial=initial,
                replace=replace,
            )
        else:
            self._config_ask_text(
                f"Token for {host}",
                draft,
                lambda text: self._config_set(draft, "token", text),
                help_lines=(
                    *(
                        (f"Your key; the vendor's own tools read it from ${draft.provider.token_env}.",)
                        if draft.provider is not None and draft.provider.token_env
                        else ("Your key for this endpoint.",)
                    ),
                    f"It is written to {self.agent.config_file}, which only you should be able to read.",
                ),
                secret=True,
                replace=replace,
            )

    def _config_ask_api(self, draft: Draft, *, replace: bool = True) -> None:
        """Ask which protocol a custom endpoint speaks."""
        rows = [ListItem(api, api.value, api.description) for api in Api]
        page = ListPage(
            rows,
            title="Which API does the endpoint speak?",
            on_select=lambda item: self._config_api_chosen(draft, cast(Api, item.value)),
            on_cancel=lambda: self._config_step_back(draft),
        )
        self._config_show(page, rows=LIST_ROWS, replace=replace)

    def _config_api_chosen(self, draft: Draft, api: Api) -> None:
        """Take the protocol picked from the list and ask the next question."""
        self._config_set(draft, "api", api)

    def _config_ask_text(
        self,
        title: str,
        draft: Draft,
        accept: Callable[[str], str | None],
        *,
        help_lines: tuple[str, ...] = (),
        secret: bool = False,
        initial: str = "",
        allow_empty: bool = False,
        replace: bool,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        """Show one line to answer; ``accept`` takes the text or answers why not.

        ``on_cancel`` is where Escape goes; by default it takes back the draft's last answer.
        """
        behind = bool(draft.trail) or draft.from_panel
        page = InputPage(
            title,
            on_submit=accept,
            on_cancel=on_cancel or (lambda: self._config_step_back(draft)),
            cancel_label="esc back" if on_cancel or behind else "esc cancel",
            help_lines=help_lines,
            secret=secret,
            initial=initial,
            allow_empty=allow_empty,
        )
        self._config_show(page, rows=INPUT_ROWS, replace=replace)

    def _config_set(self, draft: Draft, field: str, value: str) -> str | None:
        """Record one answer and move on; answer why not if it cannot be used."""
        if field == "url":
            from ...providers import check_url

            try:
                checked = check_url(value, what="the address") if value else None
            except ValueError as error:
                return str(error)
            draft.url = checked
            draft.given.add("url")
        elif field == "api":
            draft.api = Api.parse(value)
            draft.given.add("api")
        elif field == "model":
            draft.model = value
        else:
            draft.token = value
        draft.trail.append((field, "" if field == "token" else value))
        self._config_ask(draft)
        return None

    def _config_write(self, draft: Draft) -> None:
        """Write the finished draft to the file, and announce it."""
        try:
            entry = entry_for(draft)
            model = self.agent.add_configured_model(entry)
        except ValueError as error:  # ConfigEditError is one
            self._config_failed(error)
            return
        self._config_end(
            f"added {describe(entry)} \u2014 /model switches to it"
            if model is not self.agent.active_model
            else f"added {describe(entry)}"
        )

    # -- changing one --------------------------------------------------------------------
    def _config_actions(self, index: int, *, replace: bool) -> None:
        """Offer what can be done to one model."""
        try:
            model, _ = self.agent.file_models()[index]
        except (ConfigEditError, IndexError) as error:
            self._config_failed(error)
            return
        rows = [
            ListItem("use", "Use this model", "switch to it now"),
            ListItem("token", "Change the token", "the current one is not shown"),
            ListItem("api", "Change the API", f"{model.api} \u2014 chat, responses or anthropic"),
            ListItem("base_url", "Change the address", model.base_url or "default address"),
            ListItem("model", "Change the model id", model.model),
            ListItem("display_model", "Change the shown name", model.display_model or "(the model id)"),
            ListItem("multimodal", "Images", "accepted" if model.multimodal else "not accepted \u2014 text only"),
            ListItem("context_window", "Context window", tokens_text(model.context_window)),
            ListItem(
                "compact_percent",
                "Compress at",
                f"{whole_if_whole(model.compact_percent)}% of the window \u2014 {model.compaction_max_tokens:,} tokens",
            ),
            ListItem("remove", "Remove", "delete it from the file"),
        ]
        page = ListPage(
            rows,
            title=model.shown_name,
            on_select=lambda item: self._config_act(index, str(item.value)),
            on_cancel=self._config_back,
        )
        self._config_show(page, rows=ACTION_ROWS, replace=replace)

    def _config_act(self, index: int, action: str) -> None:
        """Do one of the things offered for a model."""
        try:
            model, entry = self.agent.file_models()[index]
        except (ConfigEditError, IndexError) as error:
            self._config_failed(error)
            return
        if action == "use":
            self._config_end()
            self.change_model(model)
        elif action == "remove":
            self._config_confirm_remove(index, model)
        elif action == "api":
            self._config_pick_api(index, model.api, dict(entry))
        elif action == "multimodal":
            self._config_pick_images(index, model, dict(entry))
        elif action in ("context_window", "compact_percent"):
            self._config_ask_limit(index, model, dict(entry), action)
        else:
            secret = action == "token"
            self._config_ask_text(
                {
                    "token": "New token",
                    "base_url": "New address",
                    "model": "New model id",
                    "display_model": "New shown name",
                }[action],
                Draft(),
                lambda text: self._config_change(index, dict(entry), action, text),
                help_lines=("Leave it empty to clear it.",) if action in ("base_url", "display_model") else (),
                secret=secret,
                initial="" if secret else str(entry.get(action, "")),
                allow_empty=action in ("base_url", "display_model"),
                replace=True,
                on_cancel=lambda: self._config_actions(index, replace=True),
            )

    def _config_pick_api(self, index: int, current: Api, entry: dict[str, object]) -> None:
        """Ask which protocol a model speaks, starting on the one it has."""
        rows = [ListItem(api, f"{api}{' (current)' if api == current else ''}", api.description) for api in Api]
        page = ListPage(
            rows,
            title="Which API does it speak?",
            subtitle="The address stays as it is; change it too if this host uses another.",
            on_select=lambda item: self._config_set_api(index, entry, cast(Api, item.value)),
            on_cancel=lambda: self._config_actions(index, replace=True),
            selected=list(Api).index(current),
        )
        self._config_show(page, rows=LIST_ROWS, replace=True)

    def _config_pick_images(self, index: int, model: ModelConfig, entry: dict[str, object]) -> None:
        """Ask whether a model takes images, starting on the answer it has."""
        rows = [
            ListItem(True, "Yes" + (" (current)" if model.multimodal else ""), "pictures can be attached with Ctrl-V"),
            ListItem(False, "No" + ("" if model.multimodal else " (current)"), "text only: a picture is refused"),
        ]
        page = ListPage(
            rows,
            title="Does it accept images?",
            subtitle="Only the model's documentation knows; a model that cannot read one fails the request.",
            on_select=lambda item: self._config_set_images(index, entry, bool(item.value)),
            on_cancel=lambda: self._config_actions(index, replace=True),
            selected=0 if model.multimodal else 1,
        )
        self._config_show(page, rows=LIST_ROWS, replace=True)

    def _config_set_images(self, index: int, entry: dict[str, object], accepts: bool) -> None:
        """Write whether the model takes images; the default is no, so no is written as nothing."""
        if accepts:
            entry["multimodal"] = True
        else:
            entry.pop("multimodal", None)
        refused = self._config_save(
            index, entry, lambda model: f"{model.shown_name}: images {'accepted' if accepts else 'not accepted'}"
        )
        if refused is not None:
            self._config_failed(ValueError(refused))

    def _config_ask_limit(self, index: int, model: ModelConfig, entry: dict[str, object], key: str) -> None:
        """Ask for the size of a model's window, or the share of it at which a request is summarized."""
        window = key == "context_window"
        self._config_ask_text(
            "Context window" if window else "Compress at",
            Draft(),
            lambda text: self._config_change_limit(index, entry, key, text),
            help_lines=(
                (
                    "How many tokens the model can carry: 128000, 128k or 1m.",
                    "Leave it empty to use 128,000.",
                )
                if window
                else (
                    "When the conversation fills this share of the window, it is summarized before the next request.",
                    "A percentage, more than 0 and at most 100. Leave it empty to use 80.",
                )
            ),
            initial=str(entry.get(key, "")),
            allow_empty=True,
            replace=True,
            on_cancel=lambda: self._config_actions(index, replace=True),
        )

    def _config_change_limit(self, index: int, entry: dict[str, object], key: str, text: str) -> str | None:
        """Write one of the two limits; answer why not when the text is not one."""
        if text:
            try:
                entry[key] = parse_tokens(text) if key == "context_window" else whole_if_whole(parse_percent(text))
            except ValueError as error:
                return str(error)
        else:
            entry.pop(key, None)
        return self._config_save(index, entry, lambda model: f"{model.shown_name}: {limits_text(model)}")

    def _config_save(self, index: int, entry: dict[str, object], say: Callable[[ModelConfig], str]) -> str | None:
        """Rewrite the entry in the file and in this session, and say what it came to; answer why not on a refusal."""
        try:
            model = self.agent.update_configured_model(index, entry)
        except ValueError as error:
            return str(error)
        self._config_end(say(model))
        self.app.request_layout()
        return None

    def _config_set_api(self, index: int, entry: dict[str, object], api: Api) -> None:
        """Write the protocol as the two keys the loader reads, clearing the one it no longer is."""
        for key in API_FLAG_KEYS:
            entry.pop(key, None)
        entry.update(api.keys)
        refused = self._config_save(index, entry, lambda model: f"updated {describe(entry)}")
        if refused is not None:
            self._config_failed(ValueError(refused))

    def _config_change(self, index: int, entry: dict[str, object], key: str, value: str) -> str | None:
        """Rewrite one key of one entry; answer why not when the new value is refused."""
        if value:
            if key == "base_url":
                from ...providers import check_url

                try:
                    value = check_url(value, what="the address")
                except ValueError as error:
                    return str(error)
            entry[key] = value
        else:
            entry.pop(key, None)
        return self._config_save(index, entry, lambda model: f"updated {describe(entry)}")

    def _config_confirm_remove(self, index: int, model: ModelConfig) -> None:
        """Ask once before deleting, with the safe answer first."""
        rows = [
            ListItem(False, "Keep it", ""),
            ListItem(True, f"Remove {model.shown_name}", "this edits the config file"),
        ]
        page = ListPage(
            rows,
            title="Remove this model?",
            on_select=lambda item: (
                self._config_remove(index, model) if item.value else self._config_actions(index, replace=True)
            ),
            on_cancel=lambda: self._config_actions(index, replace=True),
        )
        self._config_show(page, rows=LIST_ROWS, replace=True)

    def _config_remove(self, index: int, model: ModelConfig) -> None:
        """Remove the entry and tell the reader what is in use afterwards."""
        previous = self.agent.active_model
        try:
            now = self.agent.remove_configured_model(index)
        except ValueError as error:
            self._config_failed(error)
            return
        if previous == model and now != model:
            self.transcript.model_changed(previous.shown_name, now.shown_name)
        self._config_end(f"removed {model.shown_name}")
        self.app.request_layout()

    # -- the command line form -----------------------------------------------------------
    def config_add_from_line(self, argument: str) -> str | None:
        """Add a model from ``/config add ...``, asking only for what the line left out.

        Returns:
            A sentence when the model was added outright; ``None`` when a question was opened.

        Raises:
            ValueError: With the reason, when the line cannot be understood or the entry is refused.
        """
        draft = parse_add(argument, self.agent.providers)
        if draft.missing():
            self._config_ask(draft, replace=False)  # nothing of the flow is on screen yet
            return None
        entry = entry_for(draft)
        self.agent.add_configured_model(entry)
        return f"added {describe(entry)} \u2014 /model switches to it"

    def config_remove_from_line(self, argument: str) -> str:
        """Remove the model a number or a name picks out, for ``/config remove``."""
        entries = self.agent.file_models()
        wanted = argument.strip()
        if not wanted:
            raise ValueError("Usage: /config remove <number|name>")
        if wanted.isdigit():
            index = int(wanted) - 1
            if not 0 <= index < len(entries):
                raise ValueError(f"There is no model number {wanted}; /config list shows them")
        else:
            matches = [i for i, (model, _) in enumerate(entries) if wanted in (model.shown_name, model.model)]
            if not matches:
                raise ValueError(f"No model called {wanted!r}; /config list shows them")
            if len(matches) > 1:
                raise ValueError(f"{wanted!r} names more than one model; use its number from /config list")
            index = matches[0]
        model = entries[index][0]
        previous = self.agent.active_model
        now = self.agent.remove_configured_model(index)
        if previous == model and now != model:
            self.transcript.model_changed(previous.shown_name, now.shown_name)
        self.app.request_layout()
        return f"removed {model.shown_name}"

    def config_listing(self) -> str:
        """Return the models in the file as Markdown, with no token in it."""
        lines = [
            "| # | name | model | api | address | images | context window | compress at |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        current = self.agent.active_model
        for index, (model, _) in enumerate(self.agent.file_models(), start=1):
            mark = " (current)" if model == current else ""
            lines.append(
                f"| {index} | {model.shown_name}{mark} | `{model.model}` | {model.api} | {model.base_url or 'default'} "
                f"| {'yes' if model.multimodal else 'no'} | {model.context_window:,} "
                f"| {whole_if_whole(model.compact_percent)}% |"
            )
        return "\n".join(lines)

    def config_providers_listing(self) -> str:
        """Return the providers `/config add` accepts, as Markdown."""
        lines = ["| name | api | address | note |", "| --- | --- | --- | --- |"]
        for provider in self.agent.providers:
            note = provider.note or provider.api.description
            lines.append(f"| `{provider.name}` | {provider.api} | {provider.base_url or 'default'} | {note} |")
        lines.append(f"| `{CUSTOM}` | you choose | you give it | any endpoint |")
        return "\n".join(lines)
