"""The tool subprocess environment bridge, exposed through the engine's plugin contract."""

from zettcode.tools.shell import shell_environment, subprocess_environment

__all__ = ["shell_environment", "subprocess_environment"]
