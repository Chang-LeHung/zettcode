"""What the model is offered: the tools this client registers, and their schemas.

Every tool argument schema is built from the signature of a function in this repository, so the bundle is what this
suite can check without a request.
"""

from __future__ import annotations

import json

from zettcode.engine.extensions.files import CodingBundle


def test_every_tool_schema_stands_on_its_own():
    """No ``$ref``/``$defs``: a gateway that cannot resolve a pointer refuses the request.

    Pydantic publishes a nested argument model once and points at it from each
    use. A validator that does not follow the pointer answers the whole request
    with 400 — ``Invalid schema for function 'replace_in_file': Pointer
    '/$defs/FileEdit' does not exist`` — which is what an Anthropic-protocol
    proxy did to every turn until the runtime expanded the references. The
    expanded form is the same schema written out longhand, so nothing is lost by
    sending it: what has to hold is that no self-reference reaches the wire.

    ``edit`` used to be the tool with a nested model; it takes one change as
    three flat strings now, so the rule is checked on a bundle where nothing is
    nested, and that no nesting came back is checked with it.
    """
    schemas = {tool.name: json.dumps(tool.parameters) for tool in CodingBundle().tools}

    assert "edit" in schemas, "a rename that emptied the bundle would make this pass on nothing"
    assert '"$ref"' not in "".join(schemas.values())
    assert '"$defs"' not in "".join(schemas.values())

    props = json.loads(schemas["edit"])["properties"]
    assert set(props) == {"file_path", "old_string", "new_string", "replace_all"}
    assert props["replace_all"]["default"] is False
