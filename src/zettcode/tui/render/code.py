"""Line-oriented syntax highlighting whose colours come from a theme.

The tokenizer is deliberately small: it covers the shapes a terminal reader
actually scans for (comments, strings, numbers, keywords, called names) and
merges everything else into plain code text. Nothing here picks a colour — a
:class:`CodeTheme` supplies every one, so a palette is data, not code.

Languages are data too. Almost every language a fence can name shares the same
shapes and differs only in its word lists and markers — JavaScript's ``//``
against SQL's ``--``, quotes, keywords — so :func:`_scanner` compiles one from
that description and :data:`_SPECS` holds the descriptions: the brace languages,
the config formats, SQL, and the markup family. Python and shell keep
hand-written scanners because their lexical rules (decorators and triple
quotes; variables and command positions) do not fit the shared shape, and LaTeX
has its own because ``\\command``, math mode, and ``%`` are unlike any of them.
An unknown fence label still falls back to the generic scanner.
"""

from __future__ import annotations

import builtins
import keyword
import re
from dataclasses import dataclass

from .style import Span, Style

PYTHON = "python"
SHELL = "shell"
LATEX = "latex"
GENERIC = "generic"


@dataclass(frozen=True, slots=True)
class CodeTheme:
    """Token colours for highlighted code.

    Attributes:
        name: Palette name, shown in theme listings.
        inline: Colour of inline code spans inside Markdown prose.
        text: Colour of code that belongs to no other token class.
        keyword: Colour of language keywords.
        string: Colour of quoted literals.
        comment: Colour of comments; also drawn italic.
        number: Colour of numeric literals.
        function: Colour of a name that is immediately called.
        builtin: Colour of builtin names and the ``True``/``False``/``None`` trio.
        operator: Colour of arithmetic and comparison operators.
        punctuator: Colour of brackets, commas, and other separators.
    """

    name: str = "default"
    inline: str = "#9bddad"
    text: str = "#f2f5f3"
    keyword: str = "#e58fa8"
    string: str = "#9bddad"
    comment: str = "#6d7a70"
    number: str = "#d8b46a"
    function: str = "#7fb7d8"
    builtin: str = "#b8a6e0"
    operator: str = "#a3ada6"
    punctuator: str = "#a3ada6"

    def style_for(self, kind: str) -> Style:
        """Return the style for one token class."""
        return Style(foreground=getattr(self, kind, self.text), italic=kind == "comment")


DEFAULT_CODE_THEME = CodeTheme()

_PYTHON_TOKENS = re.compile(
    r"(?P<space>\s+)"
    r"|(?P<comment>#[^\n]*)"
    r"|(?P<string>[rbfuRBFU]{0,2}(?:'''[^\n]*|'''|\"\"\"[^\n]*|\"\"\"|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"))"
    r"|(?P<number>\b(?:0[xXbBoO][0-9a-fA-F_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?)\b)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<operator>[-+*/%=<>!&|^~]+)"
    r"|(?P<other>.)"
)

_GENERIC_TOKENS = re.compile(
    r"(?P<space>\s+)"
    r"|(?P<comment>//[^\n]*|#[^\n]*|--[^\n]*)"
    r"|(?P<string>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
    r"|(?P<number>\b\d[\d_]*(?:\.\d+)?\b)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<other>.)"
)

_SHELL_TOKENS = re.compile(
    r"(?P<space>\s+)"
    r"|(?P<comment>#[^\n]*)"
    r"|(?P<string>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
    r"|(?P<variable>\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\$[0-9@*#?!$])"
    r"|(?P<operator>\|\||&&|\d*[<>]&?\d*|[|;&<>])"
    r"|(?P<number>\b\d[\d_]*(?:\.\d+)?\b)"
    r"|(?P<name>[A-Za-z_][\w./-]*)"
    r"|(?P<other>.)"
)

_LATEX_TOKENS = re.compile(
    r"(?P<space>\s+)"
    r"|(?P<comment>%[^\n]*)"
    r"|(?P<string>\$\$[^\n]*?\$\$|\$[^$\n]*\$)"
    r"|(?P<function>\\[A-Za-z@]+|\\.)"
    r"|(?P<number>\b\d[\d_]*(?:\.\d+)?\b)"
    r"|(?P<name>[A-Za-z][A-Za-z0-9]*)"
    r"|(?P<other>.)"
)

_BUILTINS = frozenset(dir(builtins))

#: Token kinds that borrow another kind's colour.
_ALIASES = {"variable": "builtin"}

#: Shell operators that start a new command, so the next word is a command
#: name; redirections such as ``2>`` leave the following word an argument.
_SHELL_SEPARATORS = frozenset({"&&", "||", "|", ";", "&"})


def _scanner(
    *, comments: tuple[str, ...] = (), block: tuple[str, str] | None = None, quotes: str = "\"'"
) -> re.Pattern[str]:
    """Compile the scanner shared by the languages that differ only in markers.

    Args:
        comments: Prefixes that start a comment running to the end of the line.
        block: Opening and closing markers of an inline block comment; a block
            left open is treated as a comment to the end of the line, which is
            all a line-oriented highlighter can promise while text streams.
        quotes: Quote characters; a string that never closes still takes the
            rest of the line, so a half-streamed literal is not painted as code.
    """
    comment: list[str] = []
    if block is not None:
        opening, closing = block
        comment.append(rf"{re.escape(opening)}.*?(?:{re.escape(closing)}|$)")
    comment.extend(rf"{re.escape(marker)}[^\n]*" for marker in comments)
    escaped = "".join(re.escape(quote) for quote in quotes)
    parts = [r"(?P<space>\s+)"]
    if comment:
        parts.append("|(?P<comment>" + "|".join(comment) + ")")
    if escaped:
        parts.append(rf"|(?P<string>[{escaped}](?:\\.|[^\\{escaped}])*(?:[{escaped}]|$))")
    parts.append(r"|(?P<number>\b\d[\d_]*(?:\.\d+)?\b)")
    parts.append(r"|(?P<name>[A-Za-z_][\w./-]*)")
    parts.append(r"|(?P<other>.)")
    return re.compile("".join(parts))


def _words(text: str) -> frozenset[str]:
    """Return the words of one compact keyword list as a set."""
    return frozenset(text.split())


#: Keyword lists, one line per language; the scanner colours whatever it finds.
_KEYWORDS = {
    "javascript": _words(
        "async await break case catch class const continue debugger default delete do else export extends false "
        "finally for from function get if import in instanceof let new null of return set static super switch this "
        "throw true try typeof undefined var void while with yield"
    ),
    "typescript": _words(
        "abstract any as asserts async await boolean break case catch class const constructor continue declare "
        "default delete do else enum export extends false finally for from function get if implements import in "
        "infer instanceof interface is keyof let module namespace never new null number object of out override "
        "private protected public readonly return satisfies set static string super switch symbol this throw true "
        "try type typeof undefined unique unknown var void while yield"
    ),
    "rust": _words(
        "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod "
        "move mut pub ref return self Self static struct super trait true type unsafe use where while"
    ),
    "go": _words(
        "break case chan const continue default defer else fallthrough false for func go goto if import interface "
        "map nil package range return select struct switch true type var"
    ),
    "java": _words(
        "abstract assert boolean break byte case catch char class const continue default do double else enum "
        "extends false final finally float for goto if implements import instanceof int interface long native new "
        "null package private protected public return short static strictfp super switch synchronized this throw "
        "throws transient true try void volatile while"
    ),
    "c": _words(
        "auto break case char const continue default do double else enum extern false float for goto if inline int "
        "long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile "
        "while"
    ),
    "cpp": _words(
        "alignas alignof asm auto bool break case catch class concept const constexpr const_cast continue decltype "
        "default delete do double dynamic_cast else enum explicit export extern false float for friend goto if "
        "inline int long mutable namespace new noexcept nullptr operator override private protected public "
        "reinterpret_cast requires return short signed sizeof static static_assert static_cast struct switch "
        "template this thread_local throw true try typedef typename union unsigned using virtual void volatile while"
    ),
    "csharp": _words(
        "abstract as async await base bool break byte case catch char checked class const continue decimal default "
        "delegate do double else enum event explicit extern false finally fixed float for foreach goto if implicit "
        "in int interface internal is lock long namespace new null object operator out override params private "
        "protected public readonly ref return sbyte sealed short sizeof stackalloc static string struct switch this "
        "throw true try typeof uint ulong unchecked unsafe ushort using var virtual void volatile while"
    ),
    "ruby": _words(
        "alias and begin break case class def defined do else elsif end ensure false for if in module next nil not "
        "or redo rescue retry return self super then true undef unless until when while yield"
    ),
    "php": _words(
        "abstract and array as break case catch class clone const continue declare default do echo else elseif empty "
        "enddeclare endfor endforeach endif endswitch endwhile eval exit extends false final finally fn for foreach "
        "function global goto if implements include instanceof interface isset list match namespace new null or "
        "print private protected public readonly require return static switch throw trait true try unset use var "
        "while xor yield"
    ),
    "sql": _words(
        "add all alter and any as asc begin between by case cast check column commit constraint create cross default "
        "delete desc distinct drop else end exists foreign from full group having if in index inner insert into is "
        "join key left like limit not null offset on or order outer primary references right rollback select set "
        "table then transaction union unique update values view when where"
    ),
    "lua": _words(
        "and break do else elseif end false for function goto if in local nil not or repeat return then true until "
        "while"
    ),
    "haskell": _words(
        "case class data default deriving do else foreign if import in infix instance let module newtype of then "
        "type where"
    ),
    "swift": _words(
        "as associatedtype break case catch class continue default defer deinit do else enum extension fallthrough "
        "false fileprivate for func guard if import in init inout internal is let nil open operator private "
        "protocol public repeat return self static struct subscript super switch throw throws true try typealias "
        "var where while"
    ),
    "kotlin": _words(
        "abstract actual as break by catch class companion const constructor continue crossinline data delegate do "
        "dynamic else enum expect external false field file final finally for fun get if import in infix init "
        "inline inner interface internal is lateinit noinline null object open operator out override package "
        "private protected public reified return sealed set super suspend tailrec this throw true try typealias "
        "val var vararg when where while"
    ),
    "yaml": _words("true false null yes no on off"),
    "toml": _words("true false"),
    "json": _words("true false null"),
    "html": _words(
        "html head body div span a p ul ol li table thead tbody tr td th script style link meta title h1 h2 h3 h4 "
        "h5 h6 img form input button select option textarea section header footer main nav aside article code pre em "
        "strong br hr"
    ),
    "css": frozenset(),
}


@dataclass(frozen=True, slots=True)
class Language:
    """One language: its scanner and the word lists the scanner asks about.

    Attributes:
        name: Canonical name, which is what :func:`language_for` returns.
        pattern: Compiled scanner for one line.
        keywords: Words drawn with the keyword colour.
        builtins: Words drawn with the builtin colour.
        fold_case: Match the word lists case-insensitively, as SQL keywords are.
        segments: A word after an operator opens a command (the shell scanner).
    """

    name: str
    pattern: re.Pattern[str]
    keywords: frozenset[str] = frozenset()
    builtins: frozenset[str] = frozenset()
    fold_case: bool = False
    segments: bool = False


def _language(
    name: str,
    *,
    comments: tuple[str, ...] = (),
    block: tuple[str, str] | None = None,
    quotes: str = "\"'",
    fold_case: bool = False,
) -> Language:
    """Build one scanner-backed language from its markers and keyword list."""
    return Language(
        name=name,
        pattern=_scanner(comments=comments, block=block, quotes=quotes),
        keywords=_KEYWORDS.get(name, frozenset()),
        fold_case=fold_case,
    )


_SPECS: dict[str, Language] = {
    PYTHON: Language(
        name=PYTHON,
        pattern=_PYTHON_TOKENS,
        keywords=frozenset(keyword.kwlist) | {"match", "case"},
        builtins=_BUILTINS | {"True", "False", "None"},
    ),
    SHELL: Language(name=SHELL, pattern=_SHELL_TOKENS, segments=True),
    LATEX: Language(name=LATEX, pattern=_LATEX_TOKENS),
    "javascript": _language("javascript", comments=("//",), block=("/*", "*/"), quotes="\"'`"),
    "typescript": _language("typescript", comments=("//",), block=("/*", "*/"), quotes="\"'`"),
    "rust": _language("rust", comments=("//",), block=("/*", "*/")),
    "go": _language("go", comments=("//",), block=("/*", "*/"), quotes="\"'`"),
    "java": _language("java", comments=("//",), block=("/*", "*/")),
    "c": _language("c", comments=("//",), block=("/*", "*/")),
    "cpp": _language("cpp", comments=("//",), block=("/*", "*/")),
    "csharp": _language("csharp", comments=("//",), block=("/*", "*/")),
    "ruby": _language("ruby", comments=("#",)),
    "php": _language("php", comments=("#", "//"), block=("/*", "*/")),
    "sql": _language("sql", comments=("--",), block=("/*", "*/"), fold_case=True),
    "lua": _language("lua", comments=("--",), block=("--[[", "]]")),
    "haskell": _language("haskell", comments=("--",), block=("{-", "-}")),
    "swift": _language("swift", comments=("//",), block=("/*", "*/")),
    "kotlin": _language("kotlin", comments=("//",), block=("/*", "*/")),
    "yaml": _language("yaml", comments=("#",)),
    "toml": _language("toml", comments=("#",)),
    "ini": _language("ini", comments=("#", ";")),
    "json": _language("json", quotes='"', block=("/*", "*/")),
    "html": _language("html", block=("<!--", "-->")),
    "css": _language("css", block=("/*", "*/")),
}

#: Fence labels that resolve to one of the scanners above; anything else is
#: generic. Aliases exist because fences name a language in whatever way its
#: users write it — ``py``, ``python3``, ``c++``, ``yml``.
_LABELS = {
    "py": PYTHON,
    "python": PYTHON,
    "python3": PYTHON,
    "sh": SHELL,
    "bash": SHELL,
    "zsh": SHELL,
    "shell": SHELL,
    "console": SHELL,
    "make": SHELL,
    "makefile": SHELL,
    "dockerfile": SHELL,
    "docker": SHELL,
    "tex": LATEX,
    "latex": LATEX,
    "js": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "node": "javascript",
    "jsx": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "rs": "rust",
    "golang": "go",
    "h": "c",
    "cc": "cpp",
    "c++": "cpp",
    "cxx": "cpp",
    "hpp": "cpp",
    "cs": "csharp",
    "rb": "ruby",
    "yml": "yaml",
    "htm": "html",
    "xml": "html",
    "svg": "html",
    "scss": "css",
    "less": "css",
}


def language_for(label: str) -> str:
    """Map a fence label to a canonical language name.

    Args:
        label: Text after the opening fence; case and surrounding space are
            ignored, and an unknown label falls back to ``GENERIC``.
    """
    key = label.strip().lower()
    if key in _SPECS:
        return key
    return _LABELS.get(key, GENERIC)


def languages() -> tuple[str, ...]:
    """Return every language name a fence can select, in a stable order."""
    return tuple(sorted(_SPECS))


def highlight(line: str, language: str = GENERIC, theme: CodeTheme = DEFAULT_CODE_THEME) -> list[Span]:
    """Return styled spans for one line of code.

    Args:
        line: Single source line, without its trailing newline.
        language: Fence label such as ``"python"``, ``"rust"``, ``"latex"``, or
            ``"generic"``; an unknown label falls back to the generic scanner.
        theme: Palette the token colours are read from.
    """
    spec = _SPECS.get(language_for(language))
    pattern = spec.pattern if spec is not None else _GENERIC_TOKENS
    matches = list(pattern.finditer(line))
    spans: list[Span] = []
    for index, match in enumerate(matches):
        kind = match.lastgroup or "other"
        kind = _ALIASES.get(kind, kind)
        text = match.group()
        if kind == "name":
            kind = _classify_name(text, matches, index, spec)
        elif kind == "other":
            kind = "punctuator" if text.strip() else "text"
        spans.append(Span(text, theme.style_for(kind)))
    return _merge(spans)


def _classify_name(text: str, matches: list[re.Match[str]], index: int, spec: Language | None) -> str:
    """Decide whether an identifier is a keyword, a builtin, or a call target."""
    if spec is None:
        return "text"
    word = text.lower() if spec.fold_case else text
    if word in spec.keywords:
        return "keyword"
    if word in spec.builtins:
        return "builtin"
    if spec.segments:
        return "function" if _opens_a_shell_segment(matches[:index]) else "text"
    # A name that is immediately called is a function in every C-like language,
    # and in Python too; nothing else about the identifier is known.
    following = matches[index + 1].group() if index + 1 < len(matches) else ""
    return "function" if following.lstrip().startswith("(") else "text"


def _opens_a_shell_segment(previous: list[re.Match[str]]) -> bool:
    """Say whether a shell word starts a command rather than being its argument.

    A word opens a segment when nothing but whitespace precedes it, or when the
    last meaningful token is an operator such as ``&&``, ``|``, or ``;``. That
    is what colours ``cd`` and ``rm`` in ``cd /tmp && rm -rf build`` while the
    paths and flags after them stay plain text.
    """
    for match in reversed(previous):
        kind = match.lastgroup
        if kind == "space":
            continue
        return kind == "operator" and match.group() in _SHELL_SEPARATORS
    return True


def _merge(spans: list[Span]) -> list[Span]:
    """Join adjacent runs that ended up with the same style."""
    merged: list[Span] = []
    for span in spans:
        if not span.text:
            continue
        if merged and merged[-1].style == span.style:
            merged[-1] = Span(merged[-1].text + span.text, span.style)
        else:
            merged.append(span)
    return merged
