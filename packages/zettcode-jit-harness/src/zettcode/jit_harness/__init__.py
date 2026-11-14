"""The just-in-time harness of ZettCode: the plugin, the switchable extension, and the screen the reader opens.

A part of the program that lives in a distribution of its own, found through the ``zettcode.plugin`` entry point.
``[harness] jit`` in the configuration decides whether a run starts with it on (it does, unless that is ``false``). The extension (:mod:`zettcode.jit_harness.extension`)
imports the framework's harness, so nothing here imports it until the agent is built. The part also owns the panel
``/harness`` opens, and the command beside it that builds this session's tools or hands the harness back
(:mod:`zettcode.jit_harness.page`, :mod:`zettcode.jit_harness.command`), each drawn on the widget framework and the
plugin contract alone; the command is registered by the plugin, and only where there is a screen.
"""

from __future__ import annotations

from .plugin import Harness

__all__ = ["Harness"]
