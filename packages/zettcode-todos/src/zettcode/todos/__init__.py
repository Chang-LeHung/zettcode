"""The ``todo_write`` tool and the plan it keeps: the plugin that provides them to the agent and to the shell.

A part of the program that lives in a distribution of its own, found through the ``zettcode.agent`` entry point.
``[harness] todowrite`` is what gives the model the tool; the plan itself is provided as a service either way, because
the shell asks for it on every turn.
"""

from __future__ import annotations

from .plugin import TodoPlan

__all__ = ["TodoPlan"]
