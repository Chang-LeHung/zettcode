# zettcode-models

A ZettCode plugin that offers an **official model** for each vendor whose API key is in the environment:
OpenAI, Anthropic, DeepSeek and Z.AI.

Install it as an extra and enable it once:

```bash
pip install "zettcode[models]"
```

```toml
[plugins]
enable = ["models"]
```

With `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY` or `ZAI_API_KEY` set (`ZHIPUAI_API_KEY` and
`ZHIPU_API_KEY` are accepted aliases), the plugin registers that host with its current official model — `GPT-6.1 Sol`,
`Claude Opus 5.5`, `DeepSeek V4.1 Flash` or `GLM-5.3`. The model appears in `/model` with `from the openai plugin`
(or `anthropic`, `deepseek`, `zai`); its token is read from the environment and never written to `config.toml`.

The list is static and no endpoint is called at start. The plugin is off by default: a set of ambient keys should not
change a model list unless the reader asks it to.
