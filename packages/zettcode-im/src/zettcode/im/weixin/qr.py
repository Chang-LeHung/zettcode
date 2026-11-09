"""A QR code in the terminal, from the payload the login handshake carries.

Two modules of the code share one character: the top half and the bottom half are drawn as ``▀`` and ``▄``, so
a code of 33 modules is 17 lines and fits above the fold of a normal window. A terminal that cannot show those
characters still shows the link the handshake also carries, which the caller prints beside it.
"""

from __future__ import annotations

#: Columns of white around the code. Below the four a spec asks for, and above the zero that makes a scanner
#: fight the text next to it.
BORDER = 2

#: The character for each pair of modules: (top, bottom) drawn into one cell.
_CELLS = {(True, True): "\u2588", (True, False): "\u2580", (False, True): "\u2584", (False, False): " "}


def render(payload: str, *, border: int = BORDER) -> str:
    """Return ``payload`` as a QR code drawn with half-block characters, one line per two rows of modules."""
    if not payload.strip():
        raise ValueError("a QR code needs something to encode")
    import qrcode  # type: ignore[import-untyped]

    code = qrcode.QRCode(border=border, error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(payload)
    code.make(fit=True)
    matrix = code.get_matrix()
    rows = len(matrix)
    lines: list[str] = []
    for top in range(0, rows, 2):
        bottom = top + 1
        line = "".join(
            _CELLS[(bool(matrix[top][column]), bool(matrix[bottom][column]) if bottom < rows else False)]
            for column in range(len(matrix[top]))
        )
        lines.append(line)
    return "\n".join(lines)


def show(payload: str, *, border: int = BORDER) -> str:
    """Return the code with the blank line a terminal needs above and below it."""
    return "\n" + render(payload, border=border) + "\n"


__all__ = ["BORDER", "render", "show"]
