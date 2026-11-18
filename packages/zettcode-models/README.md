# zettcode-models

A ZettCode plugin that offers the vendors' **current official models** for each vendor whose API key is in the
environment: OpenAI, Anthropic, DeepSeek, Z.AI and Moonshot.

Install it as an extra:

```bash
pip install "zettcode[models]"
```

With `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `ZAI_API_KEY` or `MOONSHOT_API_KEY` set
(`ZHIPUAI_API_KEY` and `ZHIPU_API_KEY` are accepted aliases), the plugin registers that host with its official
models: `GPT-6.2 Astra` and `GPT-6.2 Sol` for OpenAI; `Claude Opus 5.5` and `Claude Sonnet 5.5` for Anthropic;
`DeepSeek V4.1 Flash` and `DeepSeek V4 Pro` for DeepSeek; `GLM-5.3` for Z.AI; `Kimi K3.1 Pro` and `Kimi K3` for
Moonshot, through its Anthropic-compatible endpoint. The models appear in `/model` with `from the openai plugin`
(or `anthropic`, `deepseek`, `zai`, `moonshot`); their tokens are read from the environment and never written to
`config.toml`.

The list is static and no endpoint is called at start. The plugin is **on by default**: a key in the environment is
enough, and a machine whose own configuration lists no model starts on the first one the plugin offers.
`[plugins] disable = ["models"]` leaves it out, and a vendor is skipped rather than failing the plugin when your
entries already show one of its models. A name an earlier plugin has taken is caught when the loader merges, so it
refuses the whole plugin, as for any plugin that overlaps another.
