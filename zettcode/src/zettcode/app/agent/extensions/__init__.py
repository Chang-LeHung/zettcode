"""What the runtime plugs into zett-agent that is ZettCode's own.

Each module here is one extension, profile, or accounting piece the runtime
(:mod:`zettcode.app.agent.runtime`) composes into a request: the tools a model can
use, an on-demand compaction, the request the next turn carries, MCP, subagents, and
token usage. They are separate modules so the runtime imports only the ones a
configuration turns on.
"""
