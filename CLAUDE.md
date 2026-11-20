# CLAUDE.md

## Project

`claude-or` is a single Bash wrapper (`./claude-or`) that launches Claude Code against
OpenRouter's Anthropic-compatible endpoint so any OpenRouter model can drive it, or
against a ChatGPT subscription (Codex backend) through an embedded local proxy. It
sets env vars, builds `CLAUDE_CODE_EXTRA_BODY`, then `exec`s `claude`. No build step,
no dependencies beyond `bash`, `python3` (stdlib only, inline `-I -c` snippets),
`md5sum`, `find`, and `claude` itself.

### Files
- `claude-or` — the whole program. Section headers are `# ---- name ----` comments.
- `system-prompt.md` — text appended to Claude Code's system prompt on every run.
- `.env` — holds `OPENROUTER_API_KEY`. Gitignored. Never read it aloud, print it, or commit it.
- `.env.example` — template for `.env`. Update it when a new env var is required.
- `.skills-plugin/` — generated at runtime (symlinks into `~/.claude/skills/synced`). Gitignored; never edit or commit.
- `changelog.txt` — release history (rules below).
- `tests/test_claude_or.py` — stdlib unittest suite (proxy translation, launch logic via a fake
  `claude` on PATH, status line). Offline; never reads `.env`. Tests are the one exception to
  "one file": they live outside the program.

### Flow of `claude-or` (top to bottom)
1. Version flag → `--statusline` mode → `TESTED_CC_VERSION` → `MODELS`/`ORDER` aliases →
   per-alias tables (`EFFORT`, `CONTEXT`, `MAXOUT`) → load `.env` → merge user aliases file →
   helpers (`or_endpoints_py` endpoint lookup with a 1-day cache, `--check-aliases`, `--doctor`).
2. Pick model (arg, number, alias, or raw ID; a leading flag or Enter uses
   `CLAUDE_OR_DEFAULT_MODEL`); split optional `@provider` pin.
3. Parse permission flags (`--auto` default, `--no-auto`, `--permission-mode`).
4. Resolve effort, context and output cap from the tables; else look up
   `https://openrouter.ai/api/v1/models/<id>/endpoints` (cached a day in `~/.cache/claude-or/endpoints/`,
   3s timeout, failures are silent).
5. Export `ANTHROPIC_*` vars pointing at OpenRouter; disable telemetry pieces individually
   (not `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, which kills session titles).
6. Rebuild `.skills-plugin/` when the synced skills manifest hash changes.
7. Auto mode: `CLAUDE_CODE_AUTO_MODE_SERVER=0` + local classifier model; reconcile provider
   pin so the classifier request is not refused. ChatGPT mode uses `gpt-6-luna`, no pins.
8. Merge provider prefs and reasoning effort into `CLAUDE_CODE_EXTRA_BODY` in one Python step
   (splice, never overwrite user JSON; a non-object body stops the launch if a merge is needed).
9. Append system prompt unless the caller passed their own.
10. Decide on the usage `statusLine` (skipped if the user has one); it calls back into
    `claude-or --statusline <backend>` (handled at the very top of the script).
11. Start the embedded stdlib proxy (`local_proxy_py`) and point `ANTHROPIC_BASE_URL`
    at it. ChatGPT mode always (Anthropic Messages → Codex Responses, auth from
    `~/.codex/auth.json`; it must write refreshed tokens back, or Codex gets logged
    out). OpenRouter mode only with the status line: a byte-for-byte pass-through
    that sums `usage.cost` per session into `~/.cache/claude-or/sessions/`.
12. Version check (cached in `~/.cache/claude-or/cc-version` until `claude` changes); `exec claude`
    (the proxy exits when that PID does).

## Conventions
- Keep it one file. Keep `set -euo pipefail` safe: guard optional vars with `${VAR:-}`,
  empty arrays with `${ARR[@]+"${ARR[@]}"}`, and `x="$(cmd | ...)"` with `|| true` when
  `cmd` may fail (a missing dir for `find` used to end the launch silently).
- Comments explain *why* (Claude Code / OpenRouter behaviour), not what. Keep that style
  when adding sections; cite the Claude Code version a behaviour was observed in.
- Python snippets: `python3 -I -c`, stdlib only, pass data via `sys.argv` (never interpolate
  into the code string), swallow network errors so launch never blocks.
- Status lines go to stderr, prefixed `→ `.
- User env vars always win over script defaults. New user-facing knobs use the
  `CLAUDE_OR_` prefix and are documented in the header comment.
- Adding an alias: update `MODELS`, `ORDER`, and `CONTEXT` (and `MAXOUT` if under
  `OUTPUT_FLOOR`, `EFFORT` if needed). Values come from OpenRouter's endpoints API for the
  pinned provider; `./claude-or --check-aliases` verifies them all.
- After changing Claude Code internals usage, retest and bump `TESTED_CC_VERSION`.

## Verifying changes
Before committing:
- `bash -n claude-or` (syntax).
- `python3 -m unittest discover -s tests` (offline). Add a test with each fix or feature.
- `shellcheck claude-or` if installed.
- `./claude-or --version` and `./claude-or --list` (no network, no claude launch).
- `./claude-or --doctor`; after alias changes, `./claude-or --check-aliases` (network).
- For launch logic, a quick real run: `./claude-or <alias> -p "say hi"`.

## Secrets
- Never hardcode keys. All secrets live in `.env`; the script loads it with `set -a`.
- Before any commit, check `git status` and `git diff --cached` for `.env`, keys
  (`sk-or-`, `sk-ant-`), or `.skills-plugin/`. If one is staged, unstage it and stop.

## Changelog and versioning rules (`changelog.txt`)
Uses [Semantic Versioning 2.0.0](https://semver.org/) and the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) structure, in plain text.

**Version bump (MAJOR.MINOR.PATCH):**
- MAJOR: breaking change for users: removed/renamed alias, flag, or `CLAUDE_OR_*` var;
  changed default behaviour (e.g. default permission mode); changed `.env` requirements.
- MINOR: backwards-compatible feature: new alias, flag, env var, or capability.
- PATCH: backwards-compatible fix: bug fix, updated model ID/context value for an existing
  alias, `TESTED_CC_VERSION` bump, comment/doc fixes that touch the script.
- Docs-only changes (README, CLAUDE.md) go under `[Unreleased]` and ship with the next release.

**Every change that touches behaviour must add a changelog line in the same commit.**
- Add lines under `[Unreleased]` in one of these groups, in this order:
  `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
- One line per change, imperative or past-tense, user-facing ("Added `kimi` alias"),
  not implementation detail. Mark breaking changes with `BREAKING:`.
- Never edit entries of a released version, except to fix typos.

**Cutting a release:**
1. Pick the version from the rules above based on everything in `[Unreleased]`.
2. Rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` and add a fresh empty `[Unreleased]` above it.
3. Set `CLAUDE_OR_VERSION="X.Y.Z"` in `claude-or` (must match the changelog).
4. Commit as `release: vX.Y.Z`, then tag: `git tag -a vX.Y.Z -m "vX.Y.Z"`.
5. Push commit and tag only when the user asks: `git push origin main --follow-tags`.

## Git
- Branch `main`; remote `origin` (GitHub). Small, focused commits.
- Commit messages: Conventional Commits style (`feat:`, `fix:`, `docs:`, `chore:`,
  `release:`), short imperative subject.
- Do not commit or push unless asked.
