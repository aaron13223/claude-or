# claude-or

Launch Claude Code against OpenRouter with any model (GPT, Grok, Gemini, DeepSeek, ...),
or against your ChatGPT subscription.

## Setup

```sh
cp .env.example .env
chmod 600 .env
# edit .env and set OPENROUTER_API_KEY
```

For the ChatGPT aliases only, skip `.env` and run `codex login` once instead.

## Usage

```sh
./claude-or                 # interactive model picker
./claude-or gpt             # use an alias
./claude-or --list          # show aliases
./claude-or --version       # print version
./claude-or x-ai/grok-4.7 -p "hi"   # any OpenRouter model ID
./claude-or chatgpt         # ChatGPT subscription instead of OpenRouter billing
./claude-or chatgpt:gpt-6-luna      # any ChatGPT/Codex model slug
```

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

### Usage status line

Each run shows usage at the bottom of Claude Code, refreshed every 30 seconds:

```
gpt-6-luna · session $0.0027 · OpenRouter $1.09 credits left · key $33.70/$50 left (monthly)
gpt-6-sol · session 26k tok, +0% 5h · ChatGPT Plus · 5h 18% used, resets 4h24m · week 3% used, resets 6d23h
```

- **session**: what this session has used so far, including side requests
  (safety classifier, titles, subagents). On OpenRouter it is the exact dollar
  cost OpenRouter reports per response; on ChatGPT, tokens plus the points of
  each plan window used since the session started (whole percents only).
  Totals are kept in `~/.cache/claude-or/sessions/`.
- On OpenRouter, this sends requests through a small local pass-through that
  forwards them unchanged; with the status line off they go direct.

Results are cached in `~/.cache/claude-or/` (60s, kept across runs). If you
already configure a `statusLine` or pass `--settings`, yours is used instead.
`CLAUDE_OR_STATUSLINE=0` turns it off.

`system-prompt.md` next to the script is appended to Claude Code's system prompt.
See the header comment in `claude-or` for all options.

See `changelog.txt` for release history.
