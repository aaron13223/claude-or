"""Tests for claude-or. Run: python3 -m unittest discover -s tests

Stdlib only, no network. Proxy tests load the Python embedded in claude-or
(local_proxy_py) without starting a server. Launch tests run a copy of the
script in a temp dir (so the real .env is never read) with a fake `claude` on
PATH that records its argv and environment instead of starting Claude Code.
"""
import base64
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "claude-or")


def embedded(func):
    src = open(SCRIPT).read()
    m = re.search(r"^%s\(\) \{\n  cat <<'PY'\n(.*?)\nPY\n\}" % re.escape(func), src, re.S | re.M)
    assert m, "no heredoc for %s() in claude-or" % func
    return m.group(1)


def load_proxy():
    ns = {"__name__": "claude_or_proxy"}
    exec(compile(embedded("local_proxy_py"), "local_proxy_py", "exec"), ns)
    return ns


def sse(*events):
    out = []
    for ev in events:
        out.append(b"data: " + json.dumps(ev).encode() + b"\n")
        out.append(b"\n")
    return out


# ---------------------------------------------------------------- proxy ----
class ProxyTranslation(unittest.TestCase):
    def setUp(self):
        self.p = load_proxy()

    def test_stream_with_reasoning_text_and_tool(self):
        lines = sse(
            {"type": "response.output_item.added", "item": {"type": "reasoning"}},
            {"type": "response.reasoning_summary_text.delta", "delta": "thinking"},
            {"type": "response.output_item.done", "item": {"type": "reasoning", "encrypted_content": "ENC"}},
            {"type": "response.output_item.added", "item": {"type": "message"}},
            {"type": "response.output_text.delta", "delta": "Hel"},
            {"type": "response.output_text.delta", "delta": "lo"},
            {"type": "response.output_item.done", "item": {"type": "message"}},
            {"type": "response.output_item.added", "item": {"type": "function_call", "call_id": "c1", "name": "Bash"}},
            {"type": "response.function_call_arguments.delta", "delta": '{"command":'},
            {"type": "response.function_call_arguments.delta", "delta": '"ls"}'},
            {"type": "response.output_item.done", "item": {"type": "function_call"}},
            {"type": "response.completed", "response": {"usage": {
                "input_tokens": 100, "output_tokens": 7, "input_tokens_details": {"cached_tokens": 40}}}},
        )
        msg, err = self.p["collect"](self.p["translate"](iter(lines), "gpt-x"))
        self.assertIsNone(err)
        kinds = [b["type"] for b in msg["content"]]
        self.assertEqual(kinds, ["thinking", "text", "tool_use"])
        think, text, tool = msg["content"]
        self.assertEqual(think["thinking"], "thinking")
        self.assertEqual(think["signature"], "cor1:" + base64.b64encode(b"ENC").decode())
        self.assertEqual(text["text"], "Hello")
        self.assertEqual(tool["input"], {"command": "ls"})
        self.assertEqual(tool["id"], "c1")
        self.assertEqual(msg["stop_reason"], "tool_use")
        self.assertEqual(msg["usage"], {"input_tokens": 60, "cache_read_input_tokens": 40, "output_tokens": 7})

    def test_block_indices_and_stops_balance(self):
        lines = sse(
            {"type": "response.output_item.added", "item": {"type": "message"}},
            {"type": "response.output_text.delta", "delta": "a"},
            {"type": "response.output_item.added", "item": {"type": "message"}},   # no done in between
            {"type": "response.output_text.delta", "delta": "b"},
            {"type": "response.completed", "response": {}},
        )
        events = list(self.p["translate"](iter(lines), "m"))
        starts = [e["index"] for n, e in events if n == "content_block_start"]
        stops = [e["index"] for n, e in events if n == "content_block_stop"]
        self.assertEqual(starts, [0, 1])
        self.assertEqual(stops, [0, 1])
        self.assertEqual(events[-1][0], "message_stop")

    def test_arguments_only_on_done(self):
        lines = sse(
            {"type": "response.output_item.added", "item": {"type": "function_call", "call_id": "c", "name": "T"}},
            {"type": "response.output_item.done", "item": {"type": "function_call", "arguments": '{"a":1}'}},
            {"type": "response.completed", "response": {}},
        )
        msg, _ = self.p["collect"](self.p["translate"](iter(lines), "m"))
        self.assertEqual(msg["content"][0]["input"], {"a": 1})

    def test_incomplete_max_tokens(self):
        lines = sse({"type": "response.incomplete", "response": {"incomplete_details": {"reason": "max_output_tokens"}}})
        msg, _ = self.p["collect"](self.p["translate"](iter(lines), "m"))
        self.assertEqual(msg["stop_reason"], "max_tokens")

    def test_failure_and_early_end_are_errors(self):
        lines = sse({"type": "response.failed", "response": {"error": {"message": "boom"}}})
        _, err = self.p["collect"](self.p["translate"](iter(lines), "m"))
        self.assertEqual(err["error"]["message"], "boom")
        _, err = self.p["collect"](self.p["translate"](iter([]), "m"))
        self.assertIn("ended early", err["error"]["message"])


class ProxyRequestConversion(unittest.TestCase):
    def setUp(self):
        self.p = load_proxy()

    def test_reasoning_round_trips_through_signature(self):
        sig = "cor1:" + base64.b64encode(b"ENC").decode()
        items = self.p["convert_input"]([{"role": "assistant", "content": [
            {"type": "thinking", "thinking": "t", "signature": sig},
            {"type": "text", "text": "hi"}]}])
        self.assertEqual(items[0], {"type": "reasoning", "summary": [{"type": "summary_text", "text": "t"}],
                                    "encrypted_content": "ENC"})
        self.assertEqual(items[1]["content"], [{"type": "output_text", "text": "hi"}])

    def test_foreign_thinking_is_dropped(self):
        items = self.p["convert_input"]([{"role": "assistant", "content": [
            {"type": "thinking", "thinking": "t", "signature": "anthropic-sig"}]}])
        self.assertEqual(items, [])

    def test_system_role_and_tool_results(self):
        items = self.p["convert_input"]([
            {"role": "system", "content": "be brief"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "c1", "name": "Read", "input": {"p": 1}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "c1", "is_error": True, "content": [
                    {"type": "text", "text": "nope"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QQ=="}}]},
                {"type": "text", "text": "next"}]},
        ])
        self.assertEqual(items[0]["role"], "developer")
        self.assertEqual(items[1], {"type": "function_call", "call_id": "c1", "name": "Read", "arguments": '{"p": 1}'})
        self.assertEqual(items[2], {"type": "function_call_output", "call_id": "c1", "output": "[tool error] nope"})
        self.assertEqual(items[3]["content"][0]["image_url"], "data:image/png;base64,QQ==")
        self.assertEqual(items[4]["content"], [{"type": "input_text", "text": "next"}])

    def test_tools_and_tool_choice(self):
        tools = self.p["convert_tools"]([
            {"name": "Bash", "description": "d", "input_schema": {"type": "object"}},
            {"type": "web_search_20250305", "name": "web_search"}])
        self.assertEqual([t["name"] for t in tools], ["Bash"])
        tc = self.p["convert_tool_choice"]
        self.assertEqual(tc(None), "auto")
        self.assertEqual(tc({"type": "any"}), "required")
        self.assertEqual(tc({"type": "tool", "name": "Bash"}), {"type": "function", "name": "Bash"})

    def test_build_request(self):
        uid = json.dumps({"session_id": "11111111-2222-3333-4444-555555555555"})
        body = {"model": "chatgpt:gpt-6-sol", "system": [{"type": "text", "text": "S"}],
                "messages": [], "output_config": {"effort": "high"}, "metadata": {"user_id": uid},
                "tool_choice": {"type": "auto", "disable_parallel_tool_use": True}}
        req = self.p["build_request"](body)
        self.assertEqual(req["model"], "gpt-6-sol")
        self.assertEqual(req["instructions"], "S")
        self.assertEqual(req["reasoning"]["effort"], "high")
        self.assertFalse(req["parallel_tool_calls"])
        self.assertEqual(req["prompt_cache_key"], self.p["build_request"](body)["prompt_cache_key"])
        body["reasoning"] = {"effort": "max"}   # claude-or's EXTRA_BODY wins over output_config
        self.assertEqual(self.p["build_request"](body)["reasoning"]["effort"], "max")

    def test_session_id(self):
        sid = "11111111-2222-3333-4444-555555555555"
        f = self.p["session_id"]
        self.assertEqual(f({"metadata": {"user_id": json.dumps({"session_id": sid})}}), sid)
        self.assertEqual(f({"metadata": {"user_id": "user_abc_account__session_" + sid}}), sid)
        self.assertIsNone(f({"metadata": {"user_id": json.dumps({"session_id": "../../etc"})}}))
        self.assertIsNone(f({}))


class ProxySessionFiles(unittest.TestCase):
    def setUp(self):
        self.p = load_proxy()
        self.tmp = tempfile.mkdtemp()
        self.p["SESS_DIR"] = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_record_accumulates(self):
        self.p["record"]("sess-0001", {"input_tokens": 10, "output_tokens": 2, "cost": 0.5})
        self.p["record"]("sess-0001", {"input_tokens": 5, "cost": 0.25})
        st = json.load(open(os.path.join(self.tmp, "sess-0001.json")))
        self.assertEqual((st["input_tokens"], st["output_tokens"], st["requests"]), (15, 2, 2))
        self.assertAlmostEqual(st["cost_usd"], 0.75)

    def test_prune_removes_only_old_files(self):
        old, new = os.path.join(self.tmp, "old.json"), os.path.join(self.tmp, "new.json")
        for p in (old, new):
            open(p, "w").write("{}")
        t = time.time() - 31 * 86400
        os.utime(old, (t, t))
        self.p["prune_sessions"]()
        self.assertEqual(os.listdir(self.tmp), ["new.json"])


# --------------------------------------------------------------- launch ----
FAKE_CLAUDE = r"""#!/usr/bin/env python3
import json, os, sys
if sys.argv[1:2] == ["--version"]:
    with open(os.environ["FAKE_CLAUDE_VERSIONS"], "a") as f:
        f.write("x")
    print(os.environ.get("FAKE_CLAUDE_VERSION", "0.0.1") + " (Claude Code)")
    sys.exit(0)
keep = [k for k in os.environ if k.startswith(("CLAUDE_CODE_", "ANTHROPIC_MODEL"))]
with open(os.environ["FAKE_CLAUDE_OUT"], "w") as f:
    json.dump({"argv": sys.argv[1:], "env": {k: os.environ[k] for k in keep}}, f)
"""


class Launch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        self.cache = os.path.join(self.tmp, "cache", "claude-or")
        self.config = os.path.join(self.tmp, "config", "claude-or")
        for d in (self.home, self.cache, self.config, os.path.join(self.tmp, "bin"), os.path.join(self.tmp, "app")):
            os.makedirs(d)
        self.script = os.path.join(self.tmp, "app", "claude-or")
        shutil.copy(SCRIPT, self.script)          # no .env or system-prompt.md beside it
        fake = os.path.join(self.tmp, "bin", "claude")
        open(fake, "w").write(FAKE_CLAUDE)
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        self.out = os.path.join(self.tmp, "claude.json")
        self.versions = os.path.join(self.tmp, "versions")
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("CLAUDE_CODE_", "CLAUDE_OR_", "ANTHROPIC_", "OPENROUTER_", "XDG_", "CODEX_"))}
        env.update(HOME=self.home, XDG_CACHE_HOME=os.path.dirname(self.cache),
                   XDG_CONFIG_HOME=os.path.dirname(self.config),
                   PATH=os.path.join(self.tmp, "bin") + os.pathsep + env.get("PATH", ""),
                   OPENROUTER_API_KEY="sk-or-test-not-a-key", CLAUDE_OR_STATUSLINE="0",
                   CLAUDE_OR_NO_VERSION_CHECK="1", CLAUDE_OR_SYSTEM_PROMPT="0",
                   FAKE_CLAUDE_OUT=self.out, FAKE_CLAUDE_VERSIONS=self.versions)
        self.env = env

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_or(self, *args, stdin="", **env):
        e = dict(self.env, **env)
        return subprocess.run([self.script, *args], input=stdin, capture_output=True, text=True,
                              env=e, cwd=self.tmp, timeout=30)

    def launched(self):
        with open(self.out) as f:
            return json.load(f)

    def seed_endpoints(self, model, eps):
        d = os.path.join(self.cache, "endpoints")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, re.sub(r"[^A-Za-z0-9._-]", "_", model) + ".json"), "w") as f:
            json.dump(eps, f)

    def body(self):
        return json.loads(self.launched()["env"]["CLAUDE_CODE_EXTRA_BODY"])

    # -- version and listing
    def test_version_matches_changelog(self):
        top = re.search(r"^\[(\d+\.\d+\.\d+)\]", open(os.path.join(ROOT, "changelog.txt")).read(), re.M)
        self.assertEqual(self.run_or("--version").stdout.strip(), "claude-or " + top.group(1))

    # -- model choice
    def test_enter_at_picker_without_default_does_not_crash(self):
        r = self.run_or(stdin="\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("No model chosen", r.stderr)
        self.assertNotIn("bad array subscript", r.stderr)

    def test_enter_at_picker_uses_default(self):
        r = self.run_or(stdin="\n", CLAUDE_OR_DEFAULT_MODEL="gpt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.launched()["env"]["ANTHROPIC_MODEL"], "openai/gpt-6.2-sol")

    def test_picker_number(self):
        self.run_or(stdin="3\n")
        self.assertEqual(self.launched()["env"]["ANTHROPIC_MODEL"], "x-ai/grok-4.7")

    def test_leading_flag_uses_default_and_keeps_args(self):
        r = self.run_or("-p", "hi", CLAUDE_OR_DEFAULT_MODEL="gpt")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = self.launched()
        self.assertEqual(got["env"]["ANTHROPIC_MODEL"], "openai/gpt-6.2-sol")
        self.assertEqual(got["argv"][-2:], ["-p", "hi"])

    def test_leading_wrapper_flag_with_default(self):
        self.run_or("--no-auto", CLAUDE_OR_DEFAULT_MODEL="gpt")
        self.assertIn("--dangerously-skip-permissions", self.launched()["argv"])

    def test_leading_flag_without_default_is_an_error(self):
        r = self.run_or("-p", "hi")
        self.assertEqual(r.returncode, 1)
        self.assertIn("CLAUDE_OR_DEFAULT_MODEL", r.stderr)

    def test_unknown_alias(self):
        r = self.run_or("nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Unknown alias", r.stderr)

    # -- CLAUDE_CODE_EXTRA_BODY
    def test_pin_and_effort_merge_into_user_body(self):
        r = self.run_or("deepseek", "--no-auto", CLAUDE_CODE_EXTRA_BODY='{"foo":1,"provider":{"sort":"price"}}')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.body(), {"foo": 1, "reasoning": {"effort": "high"}, "provider": {
            "sort": "price", "only": ["inference-net/us"], "allow_fallbacks": False}})

    def test_deepseek_default_effort_is_high(self):
        # The alias default, not just the merge: max made DeepSeek think far too long.
        r = self.run_or("deepseek", "--no-auto")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.body()["reasoning"], {"effort": "high"})

    def test_invalid_user_body_with_pin_stops_launch(self):
        r = self.run_or("deepseek", "--no-auto", CLAUDE_CODE_EXTRA_BODY="not json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a JSON object", r.stderr)
        self.assertFalse(os.path.exists(self.out))

    def test_invalid_user_body_without_merge_passes_through(self):
        self.run_or("gpt", CLAUDE_CODE_EXTRA_BODY="not json")
        self.assertEqual(self.launched()["env"]["CLAUDE_CODE_EXTRA_BODY"], "not json")

    def test_unpinned_run_drops_inherited_provider(self):
        self.run_or("gpt", CLAUDE_CODE_EXTRA_BODY='{"provider":{"only":["x"]}}')
        self.assertNotIn("CLAUDE_CODE_EXTRA_BODY", self.launched()["env"])

    def test_odd_provider_and_effort_are_valid_json(self):
        self.run_or('x/y@we"ird', "--no-auto", CLAUDE_CODE_MAX_CONTEXT_TOKENS="1000",
                    CLAUDE_CODE_MAX_OUTPUT_TOKENS="1000")
        self.assertEqual(self.body()["provider"]["only"], ['we"ird'])

    # -- auto mode classifier pin (from seeded endpoint cache, no network)
    def test_auto_mode_adds_classifier_provider(self):
        self.seed_endpoints("deepseek/deepseek-v4.1-flash-1017", [{"tag": "inference-net/us", "provider_name": "Inference.net"}])
        self.seed_endpoints("anthropic/claude-haiku-5.5", [{"tag": "anthropic", "provider_name": "Anthropic"}])
        r = self.run_or("deepseek")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.body()["provider"]["only"], ["inference-net/us", "anthropic"])
        self.assertIn("--permission-mode", self.launched()["argv"])

    # -- user aliases file
    def test_user_aliases(self):
        with open(os.path.join(self.config, "aliases"), "w") as f:
            f.write("# mine\n"
                    "mine   vendor/model-a@prov  context=5000 effort=high\n"
                    "gpt    openai/other\n"
                    "bad!   x/y\n"
                    "nomodel justaword\n")
        r = self.run_or("--list")
        self.assertIn("mine           vendor/model-a@prov", r.stdout)
        self.assertIn("openai/other", r.stdout)
        self.assertIn("bad alias name", r.stderr)
        self.assertIn("not a model ID", r.stderr)

        r = self.run_or("mine", "--no-auto")
        self.assertEqual(r.returncode, 0, r.stderr)
        env = self.launched()["env"]
        self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "5000")
        self.assertEqual(json.loads(env["CLAUDE_CODE_EXTRA_BODY"]),
                         {"provider": {"only": ["prov"], "allow_fallbacks": False}, "reasoning": {"effort": "high"}})

        # A replaced alias loses the built-in context (1050000) and is looked up instead.
        self.seed_endpoints("openai/other", [{"tag": "openai", "context_length": 12345, "max_completion_tokens": 8000}])
        self.run_or("gpt")
        env = self.launched()["env"]
        self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "12345")
        self.assertEqual(env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"], "8000")

    def test_missing_explicit_aliases_file(self):
        r = self.run_or("gpt", CLAUDE_OR_ALIASES_FILE=os.path.join(self.tmp, "none"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("CLAUDE_OR_ALIASES_FILE not found", r.stderr)

    # -- cached version check
    def test_version_check_is_cached(self):
        for _ in range(2):
            r = self.run_or("gpt", CLAUDE_OR_NO_VERSION_CHECK="", FAKE_CLAUDE_VERSION="99.0.0")
            self.assertIn("newer than tested", r.stderr)
        self.assertEqual(open(self.versions).read(), "x")   # claude --version ran once

    # -- status line rendering (fresh cache, so no network)
    def test_statusline_render(self):
        with open(os.path.join(self.cache, "usage-openrouter.json"), "w") as f:
            json.dump({"t": time.time(), "data": {"credits": {"total_credits": 10, "total_usage": 2.5},
                                                  "key": {"limit": 50, "limit_remaining": 20, "limit_reset": "monthly"}}}, f)
        os.makedirs(os.path.join(self.cache, "sessions"))
        sid = "11111111-2222-3333-4444-555555555555"
        with open(os.path.join(self.cache, "sessions", sid + ".json"), "w") as f:
            json.dump({"cost_usd": 0.01234}, f)
        r = subprocess.run([self.script, "--statusline", "openrouter"], capture_output=True, text=True,
                           input=json.dumps({"session_id": sid, "model": {"display_name": "gpt-x"}}),
                           env=dict(self.env, ANTHROPIC_BASE_URL="http://127.0.0.1:1"), timeout=30)
        self.assertEqual(r.stdout.strip(),
                         "gpt-x · session $0.0123 · OpenRouter $7.50 credits left · key $20.00/$50 left (monthly)")


if __name__ == "__main__":
    unittest.main()
