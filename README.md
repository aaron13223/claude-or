# claude-or

Launch Claude Code against OpenRouter with any model (GPT, Grok, Gemini, DeepSeek, ...),
against DeepSeek's own API, or against your ChatGPT subscription.

## Setup

```sh
cp .env.example .env
chmod 600 .env
# edit .env and set OPENROUTER_API_KEY
```

For the ChatGPT aliases only, skip `.env` and run `codex login` once instead.
For `deepseek-api`, set `DEEPSEEK_API_KEY` (no OpenRouter key needed).

## Usage

```sh
./claude-or                 # interactive model picker
./claude-or gpt             # use an alias
./claude-or --list          # show aliases
./claude-or --version       # print version
./claude-or x-ai/grok-4.7 -p "hi"   # any OpenRouter model ID
./claude-or deepseek-api    # same DeepSeek model on DeepSeek's own API
./claude-or deepseek:deepseek-v4-pro # any DeepSeek API model
./claude-or chatgpt         # ChatGPT subscription instead of OpenRouter billing
./claude-or chatgpt:gpt-6-luna      # any ChatGPT/Codex model slug
./claude-or --doctor        # check key, Codex login, Claude Code version, status line
./claude-or --check-aliases # compare alias tables with OpenRouter (maintenance)
```

Set `CLAUDE_OR_DEFAULT_MODEL` (in your shell or `.env`) to choose what Enter
picks in the menu and what runs when you start with a flag (`./claude-or -p "hi"`).

### Your own aliases

Add or replace aliases in `~/.config/claude-or/aliases` (or the file
`CLAUDE_OR_ALIASES_FILE` names) instead of editing the script:

```
# alias    model-id[@provider]                   options
mymodel    vendor/some-model@some-provider      context=128000
gpt        openai/gpt-6.2-sol                    effort=high
```

Options: `context=N`, `maxout=N`, `effort=LEVEL` (`effort=default` clears it).
Replacing a built-in alias drops its built-in context/output values; they are
then looked up from OpenRouter unless you give them.

### DeepSeek's own API

`deepseek-api` (and any `deepseek:<model>`, such as `deepseek:deepseek-v4-pro`)
runs the same model against DeepSeek's Anthropic-compatible endpoint instead of
OpenRouter. Set `DEEPSEEK_API_KEY` in `.env`; `deepseek-api` runs `deepseek-flash`,
which is the same model as the OpenRouter `deepseek` alias.

- Permission prompts are **skipped by default** here (`--dangerously-skip-permissions`):
  the auto-mode classifier would be a DeepSeek model judging its own tool calls.
  Pass `--auto` to use it anyway (classifier `deepseek-flash`; override with
  `CLAUDE_OR_CLASSIFIER_MODEL`).
- `@provider` pins don't apply, and no reasoning effort is sent by default
  (`effort=LEVEL` in your aliases file becomes `output_config.effort`).
- The status line shows your DeepSeek balance and this session's tokens.

### ChatGPT subscription

The `chatgpt` aliases and `chatgpt:<slug>` IDs bill your ChatGPT plan's Codex
usage instead of OpenRouter. They reuse the Codex CLI login (`codex login`, stored
in `~/.codex/auth.json`); no OpenRouter key is needed. A small local proxy,
started and stopped with each run, translates between Claude Code and the Codex
backend.

- `chatgpt` runs `gpt-6-sol`; `chatgpt-mini` runs `gpt-6-luna`.
- Auto mode's safety classifier runs on `gpt-6-luna`, on the same subscription
  (override with `CLAUDE_OR_CLASSIFIER_MODEL=<slug>`).
- `@provider` pins don't apply, and Claude Code's WebSearch tool is not available.
- `CLAUDE_OR_PROXY_LOG=<file>` logs proxy requests and errors.

### Browser automation with custom models

Claude in Chrome is not available through this wrapper's OpenRouter or ChatGPT
credentials. Its native extension needs a Claude Code subscription sign-in; adding
its `chrome-browser` skill would add instructions, not the browser tools. Passing
`--chrome` to `claude-or` does not remove that authentication requirement.

For browser automation with a custom model, configure an independent browser MCP
server, such as [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp).
Then start `./claude-or gpt` (or another model), check the connection with `/mcp`,
and ask Claude to use Chrome DevTools. If you have its plugin installed, you can
also invoke `/chrome-devtools-mcp:chrome-devtools`. This uses Chrome DevTools MCP,
not the Claude in Chrome extension; follow the MCP server's setup instructions to
connect it to the browser.

For native Claude in Chrome, start a separate, direct subscription session with
`claude --chrome`, signed in to the same Claude account as the extension. See
[Claude in Chrome requirements](https://code.claude.com/docs/en/chrome).

### Usage status line

Each run shows usage at the bottom of Claude Code, refreshed every 30 seconds:

```
gpt-6-luna · session $0.0027 · OpenRouter $1.09 credits left · key $33.70/$50 left (monthly)
gpt-6-sol · session 26k tok, +0% 5h · ChatGPT Plus · 5h 18% used, resets 4h24m · week 3% used, resets 6d23h
deepseek-flash · session 2.0M in (109.9M cached) + 172k out · DeepSeek $12.34 left
```

- **session**: what this session has used so far, including side requests
  (safety classifier, titles, subagents). On OpenRouter it is the exact dollar
  cost OpenRouter reports per response; on ChatGPT, tokens plus the points of
  each plan window used since the session started (whole percents only); on
  DeepSeek, tokens only (it bills from a balance, not per response), split into
  fresh input, cached input and output, since cache reads dominate long sessions
  and cost far less. Totals are kept in `~/.cache/claude-or/sessions/`.
- On OpenRouter and DeepSeek, this sends requests through a small local
  pass-through that forwards them unchanged; with the status line off they go
  direct.

Results are cached in `~/.cache/claude-or/` (60s, kept across runs). If you
already configure a `statusLine` or pass `--settings`, yours is used instead.
`CLAUDE_OR_STATUSLINE=0` turns it off.

### Tests

```sh
python3 -m unittest discover -s tests
```

Stdlib only and offline: launch tests run a copy of the script with a fake
`claude` on `PATH`, so your `.env` is never read.

`system-prompt.md` next to the script is appended to Claude Code's system prompt.
See the header comment in `claude-or` for all options.

See `changelog.txt` for release history.
