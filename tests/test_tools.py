"""What the model is offered: the tools this client registers, and their schemas.

Every tool argument schema is built by one function in the runtime, so the
filesystem bundle it produces is what this suite can check without a request.
"""

from __future__ import annotations

import json

from zett_agent.extensions.coding import CodingExtension


def test_every_tool_schema_stands_on_its_own():
    """No ``$ref``/``$defs``: a gateway that cannot resolve a pointer refuses the request.

    Pydantic publishes a nested argument model once and points at it from each
    use. A validator that does not follow the pointer answers the whole request
    with 400 — ``Invalid schema for function 'replace_in_file': Pointer
    '/$defs/FileEdit' does not exist`` — which is what an Anthropic-protocol
    proxy did to every turn until the runtime expanded the references. The
    expanded form is the same schema written out longhand, so nothing is lost by
    sending it: what has to hold is that no self-reference reaches the wire.
    """
    schemas = {tool.name: json.dumps(tool.parameters) for tool in CodingExtension().tools}

    # ``replace_in_file`` is the tool with a nested model, so it is the one whose
    # rendering this test is about; a rename that emptied the bundle would
    # otherwise make the assertions below pass on nothing.
    assert "replace_in_file" in schemas
    assert '"$ref"' not in "".join(schemas.values())
    assert '"$defs"' not in "".join(schemas.values())

    # And the nested model really is there, inlined: a field of it is described
    # where it is used, not left behind the pointer.
    edits = json.loads(schemas["replace_in_file"])["properties"]["edits"]
    assert set(edits["items"]["properties"]) >= {"old_text", "new_text"}
    assert edits["items"]["properties"]["old_text"]["description"] == "Exact text to find"
