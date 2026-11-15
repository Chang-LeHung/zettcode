"""One system message: every instruction the agent gives the model, joined into the one message before the provider.

A part of the program that lives in a distribution of its own, found through the ``zettcode.plugin`` entry point. It is
on unless ``[plugins] disable = ["one-system"]`` names it: what it changes is the shape of the request, not what the
model is told, so leaving it on is what an endpoint that accepts one system message expects.
"""

from __future__ import annotations

from .plugin import OneSystem

__all__ = ["OneSystem"]
