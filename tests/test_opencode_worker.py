"""Tests for the optional `opencode run` execution path."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import coding_agent
import orchestrator


def _events(*lines: dict) -> str:
    return "\n".join(json.dumps(line) for line in lines) + "\n"


def test_run_opencode_task_parses_events_and_writes_native_log(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    captured: dict = {}

    monkeypatch.delenv("CONTEXTCUT_OPENCODE_BIN", raising=False)
    monkeypatch.setattr(coding_agent.shutil, "which", lambda name: None)
    monkeypatch.setattr(coding_agent.Path, "home", classmethod(lambda cls: tmp_path))

    stdout = _events(
        {"type": "step_start", "part": {}},
        {"type": "text", "part": {"text": "working"}},
        {
            "type": "tool_use",
            "part": {
                "tool": "bash",
                "state": {"status": "completed", "output": "ok"},
            },
        },
        {"type": "text", "part": {"text": "final summary"}},
        {
            "type": "step_finish",
            "part": {
                "reason": "stop",
                "tokens": {"input": 10, "output": 5, "reasoning": 2},
            },
        },
    )

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(coding_agent.subprocess, "run", fake_run)
    progress: list[str] = []

    result = coding_agent.run_opencode_task(
        "do the task",
        workspace=workspace,
        agent="build",
        model="provider/model",
        timeout=12,
        progress=progress.append,
        run_root=tmp_path / "runs",
    )

    assert result.status == "done"
    assert result.output == "working\nfinal summary"
    assert result.steps == 1
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 7, "total_tokens": 17}
    assert result.workspace == str(workspace.resolve())
    assert captured["command"] == [
        "opencode",
        "run",
        "do the task",
        "--format",
        "json",
        "--agent",
        "build",
        "--model",
        "provider/model",
    ]
    assert captured["kwargs"]["cwd"] == str(workspace.resolve())
    assert captured["kwargs"]["timeout"] == 12
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True

    log = Path(result.log_path).read_text(encoding="utf-8")
    assert '"type": "tool"' in log
    assert '"type": "finish"' in log
    assert '"status": "done"' in log
    assert any("[opencode] active agent=build" in line for line in progress)
    assert any("[opencode] exit=0 status=done" in line for line in progress)


def test_run_opencode_task_missing_binary_returns_error(tmp_path, monkeypatch):
    def fake_run(command, **kwargs):
        raise FileNotFoundError("opencode")

    monkeypatch.setattr(coding_agent.subprocess, "run", fake_run)

    result = coding_agent.run_opencode_task(
        "task", workspace=tmp_path, run_root=tmp_path / "runs"
    )

    assert result.status == "error"
    assert "not found" in result.output
    assert Path(result.log_path).is_file()


def test_run_opencode_task_timeout_returns_timeout(tmp_path, monkeypatch):
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 5, output="", stderr="")

    monkeypatch.setattr(coding_agent.subprocess, "run", fake_run)

    result = coding_agent.run_opencode_task(
        "task", workspace=tmp_path, timeout=5, run_root=tmp_path / "runs"
    )

    assert result.status == "timeout"
    assert "timeout=5" in result.output


def test_run_opencode_task_nonzero_exit_is_error(tmp_path, monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="boom\n")

    monkeypatch.setattr(coding_agent.subprocess, "run", fake_run)

    result = coding_agent.run_opencode_task(
        "task", workspace=tmp_path, run_root=tmp_path / "runs"
    )

    assert result.status == "error"
    assert "status 2" in result.output


def test_run_agent_dispatches_opencode_with_plan_for_read_only(tmp_path, monkeypatch):
    calls: list[dict] = []

    def fake_opencode(prompt, **kwargs):
        calls.append({"prompt": prompt, **kwargs})
        return SimpleNamespace(to_dict=lambda: {"status": "done"})

    def fake_native(prompt, **kwargs):
        calls.append({"native": True, "prompt": prompt, **kwargs})
        return SimpleNamespace(to_dict=lambda: {"status": "done"})

    monkeypatch.setattr(coding_agent, "run_opencode_task", fake_opencode)
    monkeypatch.setattr(coding_agent, "run_task", fake_native)
    common = dict(
        workspace=tmp_path,
        model="native-model",
        base_url=None,
        api_key=None,
        max_steps=1,
        timeout=5,
        reasoning="default",
        max_tokens=1,
        ctx_limit=1,
        progress=lambda _message: None,
    )

    orchestrator.run_agent(
        "verify",
        use_opencode=True,
        agent_mode="plan",
        opencode_model="provider/model",
        opencode_cache=True,
        **common,
    )
    orchestrator.run_agent("build", use_opencode=False, **common)

    assert calls[0]["agent"] == "plan"
    assert calls[0]["model"] == "provider/model"
    assert calls[0]["cache"] is True
    assert calls[0]["workspace"] == tmp_path
    assert calls[1]["native"] is True
    assert calls[1]["model"] == "native-model"


def test_build_opencode_command_cache_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("CONTEXTCUT_OPENCODE_BIN", raising=False)
    monkeypatch.setattr(coding_agent.shutil, "which", lambda name: None)
    monkeypatch.setattr(coding_agent.Path, "home", classmethod(lambda cls: tmp_path))
    assert coding_agent.build_opencode_command("task") == [
        "opencode",
        "run",
        "task",
        "--format",
        "json",
        "--agent",
        "build",
    ]

    command = coding_agent.build_opencode_command(
        "task", agent="plan", model="provider/model", cache=True
    )
    assert command[:5] == ["opencode", "run", "task", "--format", "json"]
    assert "-c" in command
    assert command[command.index("-c") + 1 :] == ["--model", "provider/model"]

    monkeypatch.setenv("CONTEXTCUT_OPENCODE_BIN", "/custom/opencode")
    assert coding_agent.build_opencode_command("task")[0] == "/custom/opencode"


def test_parser_opencode_cache_flag_and_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("CONTEXTCUT_OPENCODE_CACHE", raising=False)
    base = ["--workspace", str(tmp_path), "--prompt", "task"]

    assert orchestrator.build_parser().parse_args(base).opencode_cache is False
    assert (
        orchestrator.build_parser().parse_args(base + ["--opencode-cache"]).opencode_cache
        is True
    )

    monkeypatch.setenv("CONTEXTCUT_OPENCODE_CACHE", "1")
    assert orchestrator.build_parser().parse_args(base).opencode_cache is True


def test_parser_use_opencode_flag_and_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("CONTEXTCUT_USE_OPENCODE", raising=False)
    base = ["--workspace", str(tmp_path), "--prompt", "task"]

    assert orchestrator.build_parser().parse_args(base).use_opencode is False
    assert orchestrator.build_parser().parse_args(base + ["--use-opencode"]).use_opencode is True

    monkeypatch.setenv("CONTEXTCUT_USE_OPENCODE", "1")
    assert orchestrator.build_parser().parse_args(base).use_opencode is True


def test_parser_reasoning_budget_and_token_defaults(tmp_path):
    base = ["--workspace", str(tmp_path), "--prompt", "task"]
    args = orchestrator.build_parser().parse_args(base + ["--reasoning-budget-tokens", "128"])
    assert args.reasoning_budget_tokens == 128
    assert orchestrator.build_parser().parse_args(base).reasoning_budget_tokens is None
    assert args.max_tokens == orchestrator.DEFAULT_MAX_TOKENS
    assert args.verifier_max_tokens == orchestrator.DEFAULT_VERIFIER_MAX_TOKENS


def test_run_agent_forwards_reasoning_budget(tmp_path, monkeypatch):
    captured = {}

    def fake_run_task(prompt, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(coding_agent, "run_task", fake_run_task)
    orchestrator.run_agent(
        "task",
        workspace=tmp_path,
        model="deepseek-v4.1-flash",
        base_url="http://192.168.137.1:8080/v1",
        api_key=None,
        max_steps=1,
        timeout=1,
        reasoning="low",
        max_tokens=16384,
        ctx_limit=32768,
        progress=lambda _: None,
        reasoning_budget_tokens=256,
    )
    assert captured["reasoning_budget_tokens"] == 256
    assert captured["max_tokens"] == 16384


def test_opencode_model_resolution_uses_mapping_and_per_agent_env(tmp_path, monkeypatch):
    monkeypatch.delenv("CONTEXTCUT_OPENCODE_MODEL", raising=False)
    monkeypatch.delenv("CONTEXTCUT_OPENCODE_MODEL_BUILD", raising=False)
    monkeypatch.delenv("CONTEXTCUT_OPENCODE_MODEL_PLAN", raising=False)
    args = argparse.Namespace(
        implementer_model="qwen3-coder:30b",
        verifier_model=None,
        opencode_model=None,
    )

    assert orchestrator._opencode_model(args, "build") is None

    monkeypatch.setenv("CONTEXTCUT_OPENCODE_MODEL", "general/model")
    assert orchestrator._opencode_model(args, "build") == "general/model"

    monkeypatch.setenv("CONTEXTCUT_OPENCODE_MODEL_BUILD", "build/model")
    assert orchestrator._opencode_model(args, "build") == "build/model"
    assert orchestrator._opencode_model(args, "plan") == "general/model"

    args.implementer_model = "provider/native"
    monkeypatch.delenv("CONTEXTCUT_OPENCODE_MODEL")
    monkeypatch.delenv("CONTEXTCUT_OPENCODE_MODEL_BUILD")
    assert orchestrator._opencode_model(args, "build") == "provider/native"


def test_run_cycle_threads_use_opencode_and_agent_modes(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
    baseline = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    calls: list[dict] = []

    def fake_run_agent(prompt, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            (Path(kwargs["workspace"]) / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            result = {"status": "done", "run_id": "impl-1", "output": "ok", "log_path": "", "steps": 1}
        else:
            result = {
                "status": "done",
                "run_id": "ver-1",
                "output": json.dumps(
                    {
                        "overall": "pass",
                        "mandates": [
                            {"id": "M1", "status": "pass", "evidence": ["app.py:1"], "issues": []}
                        ],
                        "test_integrity": {"weakened": False, "notes": "unchanged"},
                        "unresolved": [],
                    }
                ),
                "log_path": "",
                "steps": 1,
            }
        return SimpleNamespace(to_dict=lambda: result)

    monkeypatch.setattr(orchestrator, "run_agent", fake_run_agent)
    monkeypatch.setattr(orchestrator, "_run_tool_count", lambda _run_id: 1)
    args = orchestrator.build_parser().parse_args(
        [
            "--workspace",
            str(repo),
            "--prompt",
            "1. Keep the app valid.",
            "--check-command",
            "python3 -m py_compile app.py",
            "--use-opencode",
            "--artifacts-dir",
            str(tmp_path / "artifacts"),
            "--no-tts-live",
        ]
    )

    report = orchestrator._run_cycle(
        cycle=1,
        args=args,
        original_prompt="1. Keep the app valid.",
        mandates=[orchestrator.Mandate("M1", "Keep the app valid.", True)],
        artifact_dir=tmp_path / "artifacts" / "run",
        baseline=baseline,
        run_implementer=True,
        run_verifier=True,
        previous_issues=[],
        progress=lambda _message: None,
    )

    assert report["gate"]["passed"] is True, report["gate"]
    assert calls[0]["use_opencode"] is True
    assert calls[0]["agent_mode"] == "build"
    assert calls[1]["use_opencode"] is True
    assert calls[1]["agent_mode"] == "plan"
