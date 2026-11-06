"""The just-in-time harness of ZettCode: the plugin, the switchable extension, and the screen the reader opens.

A part of the program that lives in a distribution of its own, found through the ``zettcode.plugin`` entry point.
``[harness] jit`` in the configuration is what turns it on. The extension (:mod:`zettcode.jit_harness.extension`)
imports the framework's harness, so nothing here imports it until the agent is built. The part also owns the read-only
page ``/harness`` opens (:mod:`zettcode.jit_harness.page`) and the command that opens it
(:mod:`zettcode.jit_harness.command`), each drawn on the widget framework and the plugin contract alone; the command is
registered by the plugin, and only where there is a screen.
"""

from __future__ import annotations

from .plugin import Harness

__all__ = ["Harness"]
