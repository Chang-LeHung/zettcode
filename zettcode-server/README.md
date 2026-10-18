# zettcode-server

The HTTP face of the ZettCode coding agent, in the same repository as the terminal program and its Python SDK.

The package is the second member of the workspace, next to [`zettcode/`](../zettcode). It is built against the released
`zettcode` SDK and holds no agent of its own: one process serves one workspace, and every request drives the same
runtime the terminal does.
