"""The coding tools the agent offers, written here: read, search, write, edit and the shell.

``files`` holds the six file tools and ``shell`` the seventh; ``workspace``, ``output`` and ``images`` are what they are
built from; ``boundary`` is the contract the shell tool has with the permission level. Nothing here is re-exported,
so importing the package costs nothing: ``boundary`` is imported by the permission package at start-up and has to stay
free of the schema library the tools themselves need.
"""
