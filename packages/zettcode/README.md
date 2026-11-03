# ZettCode

A focused terminal coding agent powered by [zett-agent](https://pypi.org/project/zett-agent/): it reads and edits your
code, runs commands with your permission, and is driven by a model you choose. The repository also ships a Python SDK
and an HTTP server.

```bash
pip install zettcode
zettcode
```

- [The guide](https://chang-lehung.github.io/zettcode/) — commands, keys, plugins, configuration
- [The SDK](https://chang-lehung.github.io/zettcode/sdk/) — drive the agent from Python
- [The server](https://chang-lehung.github.io/zettcode/server/) — drive it over HTTP

The full README, with the screenshots, is at the root of the repository.

```python
import zettcode.sdk as zc

result = await zc.prompt("summarize the README", permission="deny")
print(result.text)
```
