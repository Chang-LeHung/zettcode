"""The integrations the SDK adds to the engine, loaded only by a runtime that asks for them.

The engine's own extensions are the machinery a request is made of. These are the ones that need something the engine
must not carry: the broker (messaging), `tiktoken` (context counting), and the MCP client. The builtins in
:mod:`zettcode.sdk.builtins` register them, so an embedding that uses the engine directly decides for itself.
"""
