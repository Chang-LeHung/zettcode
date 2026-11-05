"""The just-in-time harness of ZettCode: the plugin that registers it and the switchable extension it hands the agent.

A part of the program that lives in a distribution of its own, found through the ``zettcode.agent`` entry point.
``[harness] jit`` in the configuration is what turns it on. The extension (:mod:`zettcode.harness.extension`) imports
the framework's harness, so nothing here imports it until the agent is built.
"""

from __future__ import annotations

from .plugin import Harness

__all__ = ["Harness"]
