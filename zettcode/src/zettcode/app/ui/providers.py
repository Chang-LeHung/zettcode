"""``/config``: add, change and remove the models in the config file from inside the shell.

The pages are the shell's usual ones — a list to choose from, a form to fill in — stacked one after another; this
module is the order they come in. Each step replaces the page before it, Escape on any step abandons the whole thing,
and nothing is written until the last answer is in. What is written is decided by :mod:`.config_form` and
:mod:`zettcode.config_edit`; what this module adds is only the sequence and the sentence the reader is left with.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, cast

from zettcode.providers import API_FLAG_KEYS, CUSTOM, Api, check_url
from zettcode.sdk.errors import ConfigurationError
from zettcode.tui import SEPARATOR, ListItem, ListPage, Screen, Widget

from ..agent.conversation.text import compact_path
from .config_form import (
    Draft,
    describe,
    entry_for,
    limits_text,
    parse_add,
    parse_percent,
    parse_temperature,
    parse_tokens,
    whole_if_whole,
)
from .shell import PAGE_SCREEN, ShellState
from .widgets import Field, FormPage, ModelSettingsPage, bottom_panel, form_rows, model_settings_rows
from .widgets.model_settings_page import Action, Answer, Setting

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.providers import Provider
    from zettcode.sdk.types import ModelInfo

#: Rows the list pages take: the title, a blank, up to eight rows, the keys.
LIST_ROWS = 13

#: Columns the file's path may take under the title; a longer one keeps its end, where the name is.
SUBTITLE_COLUMNS = 70


class _Refused(Exception):
    """A change the file would not take, and the row of the panel that has to be corrected for it to be."""

    def __init__(self, key: str, reason: str) -> None:
        """Hold the key of the row (empty when it is none) and the sentence that says what is wrong."""
        super().__init__(reason)
        self.key = key
        self.reason = reason


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
        entries = self.client.model_entries()
        digits = len(str(len(entries)))
        rows = [
            ListItem(
                index,
                f"{index + 1:>{digits}}. {model.name}{' (current)' if model.active else ''}",
                f"{model.model} {SEPARATOR} {model.api} {SEPARATOR} {model.base_url or 'default address'}",
            )
            for index, (model, _) in enumerate(entries)
        ]
        rows.append(ListItem(None, "+ Add a model", "from a provider, or any endpoint"))
        page = ListPage(
            rows,
            title="Models",
            subtitle=compact_path(self.client.config_file, limit=SUBTITLE_COLUMNS),
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
        except ConfigurationError as error:
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
        """Escape in the form: take back the last choice made before it and ask it again.

        That choice is the protocol of a custom endpoint, the one thing asked on a page of its own. With none behind
        it, Escape goes to the provider list when the flow came from there, and closes when it was started from a
        typed line, which has nothing behind it.
        """
        previous = draft.undo()
        if previous is not None:
            self._config_ask(draft)
        elif draft.from_panel:
            self._config_pick_provider(replace=True)
        else:
            self._config_end()

    def _config_ask(self, draft: Draft, *, replace: bool = True) -> None:
        """Ask for what a draft is missing, or write it when nothing is.

        A custom endpoint is asked which protocol it speaks, on a list of its own, because that is a choice among three
        words and not text. Everything else is one form: the model id, the token, the address and a name, with the cursor
        moving between them by Tab and Enter saving all of it.

        Args:
            draft: What is known so far.
            replace: Whether a page of this flow is on screen to be replaced. The form of ``/config add`` typed with
                something left out has none.
        """
        wanted = draft.missing()
        if not wanted:
            self._config_write(draft)
        elif wanted[0] == "api":
            self._config_ask_api(draft, replace=replace)
        else:
            self._config_add_form(draft, replace=replace)

    def _config_add_form(self, draft: Draft, *, replace: bool) -> None:
        """Show the form that adds a model: only the model id has to be filled in."""
        host = draft.provider.label if draft.provider is not None else "a custom endpoint"
        suggestions = draft.provider.models if draft.provider is not None else ()
        token_note = (
            f"Your key; the vendor's own tools read it from ${draft.provider.token_env}. Leave it empty for a local server."
            if draft.provider is not None and draft.provider.token_env
            else "Your key for this endpoint. Leave it empty for a local server, or to use the environment's."
        )
        fields = [
            Field(
                "model",
                "Model id",
                initial=draft.model,
                placeholder=suggestions[0] if suggestions else "",
                hint="The id the provider calls the model, exactly as its documentation writes it."
                + (f" For example: {', '.join(suggestions[:3])}" if suggestions else ""),
                required=True,
            ),
            Field(
                "token",
                "Token",
                initial=draft.token,
                placeholder="optional",
                hint=f"{token_note} It is written to {self.client.config_file}.",
                secret=True,
            ),
        ]
        if draft.api is not Api.ANTHROPIC:
            fields.append(
                Field(
                    "url",
                    "Address",
                    initial=draft.url or "",
                    placeholder="default address" if not draft.custom else "https://api.example.com/v1",
                    hint="The address the client appends its route to, such as https://api.example.com/v1.",
                    required=draft.custom,
                )
            )
        fields.append(
            Field(
                "name",
                "Shown name",
                initial=draft.name,
                placeholder="the model id",
                hint="What the header and /model show for it. Leave it empty to show the model id.",
            )
        )
        fields.append(
            Field(
                "temperature",
                "Temperature",
                initial="" if draft.temperature is None else f"{whole_if_whole(draft.temperature)}",
                placeholder="the provider's default",
                hint="How random the answers are, from 0 (the most deterministic) to "
                + ("1." if draft.api is Api.ANTHROPIC else "2.")
                + " Leave it empty to send none.",
            )
        )
        page = FormPage(
            f"Add a model at {host}",
            fields,
            on_submit=lambda values: self._config_added(draft, values),
            on_cancel=lambda: self._config_step_back(draft),
            cancel_label="esc back" if draft.trail or draft.from_panel else "esc cancel",
        )
        self._config_show(page, rows=form_rows(len(fields)), replace=replace)

    def _config_added(self, draft: Draft, values: dict[str, str]) -> tuple[str, str] | None:
        """Take the form's answers into the draft and write it; answer which line is wrong when one is."""
        address = values.get("url", "")
        if address:
            try:
                checked = check_url(address, what="the address")
            except ValueError as error:
                return ("url", str(error))
            draft.url = checked
        elif draft.api is not Api.ANTHROPIC:
            draft.url = None
        draft.given.add("url")
        draft.model = values["model"]
        draft.token = values["token"]
        draft.name = values["name"]
        if values["temperature"]:
            try:
                draft.temperature = parse_temperature(values["temperature"], draft.api)
            except ValueError as error:
                return ("temperature", str(error))
        else:
            draft.temperature = None
        draft.given.add("token")
        self._config_write(draft)
        return None

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
        """Take the protocol picked from the list and ask the rest on one form."""
        draft.api = Api.parse(api)
        draft.chat = draft.api is Api.CHAT
        draft.given.add("api")
        draft.trail.append(("api", api.value))
        self._config_ask(draft)

    def _config_write(self, draft: Draft) -> None:
        """Write the finished draft to the file, and announce it.

        The first model a machine ever has is the one requests go to from then on — there was nothing for it to
        be added beside — so that one is announced as being in use rather than as one more to switch to.
        """
        first = self.model is None
        try:
            entry = entry_for(draft)
            model = self.client.add_model(entry)
        except ValueError as error:  # ConfigurationError is one
            self._config_failed(error)
            return
        if first:
            self._warm_runtime()
            self._config_end(f"added {describe(entry)} \u2014 this is the model requests now use")
        elif model.name != self.client.model.name:
            self._config_end(f"added {describe(entry)} \u2014 /model switches to it")
        else:
            self._config_end(f"added {describe(entry)}")

    # -- changing one --------------------------------------------------------------------
    def _config_actions(self, index: int, *, replace: bool) -> None:
        """Show every setting of one model on one page, with what can be done to it under them.

        The names are on the left and the values on the right: what is typed is an editor, whether images are accepted
        and whether the provider searches the web are switches, the API is a choice among its three. Enter saves all of
        them at once; the two actions at the bottom are switching to the model and removing it.
        """
        try:
            model, entry = self.client.model_entries()[index]
        except (ConfigurationError, IndexError) as error:
            self._config_failed(error)
            return
        settings = [
            Setting(
                "token",
                "Token",
                "secret",
                placeholder="unchanged",
                hint="Your key. The current one is never shown; leave this empty to keep it.",
            ),
            Setting(
                "api",
                "API",
                "choice",
                words=tuple(api.value for api in Api),
                value=list(Api).index(Api.parse(model.api)),
                hint="The protocol the endpoint speaks. The address stays as it is; change it too if this host uses another.",
            ),
            Setting(
                "base_url",
                "Address",
                initial=str(entry.get("base_url", "")),
                placeholder="default address",
                hint="Where requests go, such as https://api.example.com/v1. Leave it empty for the API's own.",
            ),
            Setting(
                "model",
                "Model id",
                initial=str(entry.get("model", "")),
                hint="The id the provider calls the model, exactly as its documentation writes it.",
                required=True,
            ),
            Setting(
                "display_model",
                "Shown name",
                initial=str(entry.get("display_model", "")),
                placeholder="the model id",
                hint="What the header and /model show for it. Leave it empty to show the model id.",
            ),
            Setting(
                "multimodal",
                "Images",
                "switch",
                words=("text only", "accepted"),
                value=int(model.multimodal),
                hint="Only the model's documentation knows; a model that cannot read a picture fails the request.",
            ),
            Setting(
                "web_search",
                "Web search",
                "switch",
                words=("off", "on"),
                value=int(model.web_search),
                hint="The endpoint runs the search; ZettCode fetches nothing."
                + ("" if model.can_search else " DeepSeek searches only over the Anthropic API."),
            ),
            Setting(
                "web_search_name",
                "Search tool",
                initial=str(entry.get("web_search_name", "")),
                placeholder=f"the default: {model.search_name}",
                hint="The exact tool type the endpoint expects. Leave it empty to send the default for the API.",
            ),
            Setting(
                "temperature",
                "Temperature",
                initial=str(entry.get("temperature", "")),
                placeholder="the provider's default",
                hint=f"From 0 (the most deterministic) to {1 if model.api == 'anthropic' else 2}. Leave it empty to send none.",
            ),
            Setting(
                "context_window",
                "Context window",
                initial=str(entry.get("context_window", "")),
                placeholder="128,000 tokens",
                hint="How many tokens the model can carry: 128000, 128k or 1m. Leave it empty to use 128,000.",
            ),
            Setting(
                "compact_percent",
                "Compress at",
                initial=str(entry.get("compact_percent", "")),
                placeholder="80 (% of the window)",
                hint="When the conversation fills this share of the window it is summarized first: more than 0, at most 100.",
            ),
        ]
        actions = [
            Action("use", "Use this model", "save any change, then switch to it now", saves=True),
            Action("remove", "Remove", "delete it from the file"),
        ]
        page = ModelSettingsPage(
            f"{model.name}{' (current)' if model.active else ''}",
            settings,
            actions,
            on_save=lambda values: self._config_saved(index, values),
            on_action=lambda action, values: self._config_acted(index, action, values),
            on_cancel=self._config_back,
        )
        self._config_show(page, rows=model_settings_rows(len(settings), len(actions)), replace=replace)

    def _config_saved(self, index: int, values: dict[str, Answer]) -> tuple[str, str] | None:
        """Write what the page holds, and close it; answer which row is wrong when one is."""
        try:
            model, entry, before = self._config_update(index, values)
        except _Refused as refused:
            return (refused.key, refused.reason)
        except (ConfigurationError, IndexError) as error:
            self._config_failed(error)
            return None
        if entry == before:
            self._config_end(f"{model.name}: nothing changed")
        else:
            limits = any(entry.get(key) != before.get(key) for key in ("context_window", "compact_percent"))
            self._config_end(f"updated {describe(entry)}" + (f" {SEPARATOR} {limits_text(model)}" if limits else ""))
        self.app.request_layout()
        return None

    def _config_acted(self, index: int, action: Action, values: dict[str, Answer]) -> tuple[str, str] | None:
        """Do what one of the page's actions says: switch to the model, after saving it, or ask about removing it."""
        try:
            if action.key == "remove":
                model, _ = self.client.model_entries()[index]
                self._config_confirm_remove(index, model)
                return None
            model, _, _ = self._config_update(index, values)
        except _Refused as refused:
            return (refused.key, refused.reason)
        except (ConfigurationError, IndexError) as error:
            self._config_failed(error)
            return None
        self._config_end()
        self.change_model(model)
        return None

    def _config_update(
        self, index: int, values: dict[str, Answer]
    ) -> tuple[ModelInfo, dict[str, object], Mapping[str, object]]:
        """Rewrite the entry the page was opened on with every answer it holds, in the file and in this session.

        Only what differs from the entry is touched: a key the reader never changed is not written, and an empty row
        removes its key so the default applies. The token is the exception to "empty clears": the current one is never
        shown, so an empty row means it was left alone.

        Returns:
            The model as it is now, the entry as written, and the entry as it was.

        Raises:
            _Refused: With the row to correct, when an answer is not one the model can take.
        """
        model, current = self.client.model_entries()[index]
        entry = dict(current)
        api = Api.parse(str(values["api"]))
        if api != Api.parse(model.api):
            for key in API_FLAG_KEYS:
                entry.pop(key, None)
            entry.update(api.keys)
            if api is Api.CHAT:
                entry["chat"] = True
        readers: dict[str, Callable[[str], object]] = {
            "base_url": lambda text: check_url(text, what="the address"),
            "temperature": lambda text: whole_if_whole(parse_temperature(text, api)),
            "context_window": parse_tokens,
            "compact_percent": lambda text: whole_if_whole(parse_percent(text)),
        }
        for key in (
            "base_url",
            "model",
            "display_model",
            "web_search_name",
            "temperature",
            "context_window",
            "compact_percent",
        ):
            text = str(values[key])
            if text == str(current.get(key, "")):
                continue  # a row the reader did not touch is not rewritten, however the file happens to spell it
            try:
                self._set(entry, key, readers.get(key, str)(text) if text else None)
            except ValueError as error:
                raise _Refused(key, str(error)) from None
        if values["token"]:
            entry["token"] = str(values["token"])
        self._set(entry, "multimodal", True if values["multimodal"] else None)
        self._set(entry, "web_search", True if values["web_search"] else None)
        if entry == current:
            return model, entry, current
        try:
            # The page holds the whole entry it wants; the SDK takes what to change, and a key the entry no longer
            # has is one to remove.
            changes = {**entry, **{key: None for key in current if key not in entry}}
            return self.client.update_model(index, changes), entry, current
        except ValueError as error:
            sentence = str(error).lower()
            raise _Refused(
                next((key for key in ("temperature", "search") if key in sentence), ""), str(error)
            ) from None

    @staticmethod
    def _set(entry: dict[str, object], key: str, value: object | None) -> None:
        """Set a key, or take it out of the entry when there is nothing to say."""
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value

    def _config_confirm_remove(self, index: int, model: ModelInfo) -> None:
        """Ask once before deleting, with the safe answer first."""
        rows = [
            ListItem(False, "Keep it", ""),
            ListItem(True, f"Remove {model.name}", "this edits the config file"),
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

    def _config_remove(self, index: int, model: ModelInfo) -> None:
        """Remove the entry and tell the reader what is in use afterwards."""
        previous = self.model
        try:
            now = self.client.remove_model(index)
        except ValueError as error:
            self._config_failed(error)
            return
        if previous is not None and previous.name == model.name and now.name != model.name:
            self.transcript.model_changed(previous.name, now.name)
        self._config_end(f"removed {model.name}")
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
        first = self.model is None
        entry = entry_for(draft)
        self.client.add_model(entry)
        if first:
            self._warm_runtime()
            return f"added {describe(entry)} \u2014 this is the model requests now use"
        return f"added {describe(entry)} \u2014 /model switches to it"

    def config_remove_from_line(self, argument: str) -> str:
        """Remove the model a number or a name picks out, for ``/config remove``."""
        entries = self.client.model_entries()
        wanted = argument.strip()
        if not wanted:
            raise ValueError("Usage: /config remove <number|name>")
        if wanted.isdigit():
            index = int(wanted) - 1
            if not 0 <= index < len(entries):
                raise ValueError(f"There is no model number {wanted}; /config list shows them")
        else:
            matches = [i for i, (model, _) in enumerate(entries) if wanted in (model.name, model.model)]
            if not matches:
                raise ValueError(f"No model called {wanted!r}; /config list shows them")
            if len(matches) > 1:
                raise ValueError(f"{wanted!r} names more than one model; use its number from /config list")
            index = matches[0]
        model = entries[index][0]
        previous = self.model
        now = self.client.remove_model(index)
        if previous is not None and previous.name == model.name and now.name != model.name:
            self.transcript.model_changed(previous.name, now.name)
        self.app.request_layout()
        return f"removed {model.name}"

    def config_listing(self) -> str:
        """Return the models in the file as Markdown, with no token in it."""
        lines = [
            "| # | name | model | api | address | images | context window | compress at |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for index, (model, _) in enumerate(self.client.model_entries(), start=1):
            mark = " (current)" if model.active else ""
            lines.append(
                f"| {index} | {model.name}{mark} | `{model.model}` | {model.api} | {model.base_url or 'default'} "
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
