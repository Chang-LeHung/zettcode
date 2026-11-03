"""The two things a message from another session carries that the broker and the application share.

The broker carries a message; the application stores and draws one. Both need to say how it arrived (``via``) and,
for a direct message, to carry a picture. The words and the picture live here — a leaf with no imports of ours — so
the broker can speak them without importing the message type, which pulls in the agent runtime.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

#: How a message reached its recipient: a reader typed it into another session, an agent used its tool, or it came
#: from something that is not a ZettCode session at all. The broker speaks the same words when it carries one, so a
#: relayed message and the wire cannot drift apart.
VIA_USER = "user"
VIA_AGENT = "agent"
VIA_EXTERNAL = "external"


@dataclass(frozen=True, slots=True)
class ImageData:
    """One picture a message carries: its media type and the encoded file (not decoded pixels)."""

    media_type: str
    data: bytes

    def to_wire(self) -> dict[str, str]:
        """Return the picture as a line carries it: the media type and the file in base64."""
        return {"media_type": self.media_type, "data": base64.b64encode(self.data).decode("ascii")}
