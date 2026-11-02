"""Where a tool's guidance goes: with the tool, in its own description, and with what it returns.

Every agent this application builds (the main one and each sub-agent) carries its tools' snippets and guidelines the
same way, so the choice is made once here. The guidance is one line of prose beside the tool's description in the
request's tool definitions, not a pair of sections in the system prompt, which keeps it next to the tool wherever the
definition goes (a deferred tool found through tool search, an endpoint that shows the model only the definitions).
The tools' return types are described there too: a tool that returns something with a shape says what shape.
"""

from __future__ import annotations

from zett_agent.extensions.tool_guidelines import ToolGuidancePlacement, ToolGuidelinesExtension


def tool_guidance() -> ToolGuidelinesExtension:
    """Return the extension that folds each tool's snippet, guidelines and return type into its description."""
    return ToolGuidelinesExtension(placement=ToolGuidancePlacement.DESCRIPTION, returns=True)
