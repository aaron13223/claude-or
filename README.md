# claude-or

Launch Claude Code against OpenRouter with any model (GPT, Grok, Gemini, DeepSeek, ...).

## Setup

```sh
cp .env.example .env
chmod 600 .env
# edit .env and set OPENROUTER_API_KEY
```

## Usage

```sh
./claude-or                 # interactive model picker
./claude-or gpt             # use an alias
./claude-or --list          # show aliases
./claude-or --version       # print version
./claude-or x-ai/grok-4.7 -p "hi"   # any OpenRouter model ID
```

`system-prompt.md` next to the script is appended to Claude Code's system prompt.
See the header comment in `claude-or` for all options.

See `changelog.txt` for release history.
