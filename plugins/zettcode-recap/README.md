# zettcode-recap

A ZettCode plugin. It adds `/recap`, and writes one on its own when you step away.

A recap is one sentence about where the session is: the goal, what is done, and the next thing to do. It is for a
reader coming back to a long conversation — the model's own context is not touched, and neither the question nor the
answer is stored as part of the conversation.

- **`/recap`** writes one now, whatever the clock says. It needs a request to have finished. While the model answers,
  the pinned row says `Recap … writing`, and Ctrl-C or Escape stops it; the answer follows as a quoted message.
- **On its own**, once no new turn has started for long enough and the conversation is worth summarising: at least 3
  messages you typed, and at least 2 since the last recap. The delay is `min(after_seconds, 0.8 × cache_ttl_seconds)`,
  which is 180 seconds by default (the provider's prompt cache is likely cold by then, so waiting longer only costs
  more). Any new turn cancels a recap that is waiting or being written: it would be news about a conversation that
  has moved on. It is the reader's own activity that is measured, not the window — somebody reading the last answer
  is still there, and somebody who switched to another application after a turn is as idle as one reading.

The summary is requested with `cache="read"`: the conversation's warm prompt-cache prefix is reused, and the recap's
own words are not written into the cache. It runs with no tools, a 60-second deadline, and a prompt that asks for
under 40 words and no markdown.

## Settings

Each setting has a default and can be overridden in `config.toml`; your value wins:

```toml
[plugins.recap]
after_seconds = 180       # how long no new turn may start
cache_ttl_seconds = 300   # the provider's prompt-cache lifetime; the delay is 0.8 of it
min_messages = 3          # messages you typed before a recap is worth writing
min_since_recap = 2       # and messages since the last one
```

A value of the wrong type is refused when the plugin loads, naming the table and the key.

The automatic recap needs nothing of the terminal but turns; the focus hook the shell offers is not used. A recap
waiting when the program exits ends with it.

## Install

From a checkout of this repository:

    uv tool install --force --with ./plugins/zettcode-recap zettcode

or, with pip in the environment ZettCode runs in:

    pip install ./plugins/zettcode-recap

There is no `zettcode[recap]` extra yet: the plugin has not been released, and an extra that names a package no index
carries would break `pip install "zettcode[recap]"`. The release workflow is in place (`recap-v*`), and the extra
lands with the first release.

It runs on ZettCode 0.3 and later (`zettcode>=0.3,<0.4`), whose terminal group has the turn hooks this plugin is
built on.
