"""Tests for the two-agent orchestrator."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import orchestrator


def test_extract_mandates_required_and_optional():
    prompt = """MUST FIX:
1. Serve the admin UI.
   - Use FileResponse.
2. Serve the listener UI.
   - Preserve the room query.

ONLY IF STEP/TIME BUDGET REMAINS:
7. Optional triangulation.
8. Optional detector wiring.

VERIFY:
python3 -m pytest -q
"""
    mandates = orchestrator.extract_mandates(prompt)

    assert [mandate.id for mandate in mandates] == ["M1", "M2", "M3", "M4"]
    assert [mandate.required for mandate in mandates] == [True, True, False, False]
    assert "FileResponse" in mandates[0].text
    assert "room query" in mandates[1].text


def test_load_mandates_validates_and_preserves_required(tmp_path):
    path = tmp_path / "mandates.json"
    path.write_text(
        json.dumps(
            [
                {"id": "M1", "text": "Do a thing", "required": True},
                {"text": "Optional thing", "required": False},
            ]
        ),
        encoding="utf-8",
    )

    mandates = orchestrator.load_mandates(path)

    assert mandates[0].id == "M1"
    assert mandates[0].required is True
    assert mandates[1].required is False


def test_parse_verifier_report_fenced_json():
    text = """Verification follows.

```json
{
  "overall": "pass",
  "mandates": [{"id": "M1", "status": "pass"}],
  "test_integrity": {"weakened": false},
  "unresolved": []
}
```
"""
    report = orchestrator.parse_verifier_report(text)

    assert report is not None
    assert report["overall"] == "pass"
    assert report["mandates"][0]["id"] == "M1"


def test_parse_verifier_report_returns_none_without_json():
    assert orchestrator.parse_verifier_report("no json here") is None


def _passing_report(optional_status: str = "pass") -> dict:
    return {
        "overall": "pass",
        "mandates": [
            {"id": "M1", "status": "pass", "evidence": ["app.py:54"], "issues": []},
            {"id": "M2", "status": optional_status, "evidence": ["TODO.md"], "issues": []},
        ],
        "test_integrity": {"weakened": False, "notes": "checked"},
        "unresolved": [],
    }


def test_gate_report_passes_required_and_deferred_optional():
    mandates = [
        orchestrator.Mandate("M1", "required", True),
        orchestrator.Mandate("M2", "optional", False),
    ]
    checks = [orchestrator.CheckResult("pytest", "python3 -m pytest -q", True)]

    gate = orchestrator.gate_report(
        _passing_report("deferred"),
        mandates,
        checks,
        todo_present=True,
        verifier_status="done",
        verifier_read_only=True,
    )

    assert gate.passed is True
    assert gate.failures == []


def test_gate_report_fails_deferred_optional_without_todo():
    mandates = [
        orchestrator.Mandate("M1", "required", True),
        orchestrator.Mandate("M2", "optional", False),
    ]
    checks = [orchestrator.CheckResult("pytest", "python3 -m pytest -q", True)]

    gate = orchestrator.gate_report(
        _passing_report("deferred"),
        mandates,
        checks,
        todo_present=False,
        verifier_status="done",
        verifier_read_only=True,
    )

    assert gate.passed is False
    assert any("TODO.md is missing" in failure for failure in gate.failures)


def test_gate_report_fails_required_unknown_and_deterministic_failure():
    mandates = [orchestrator.Mandate("M1", "required", True)]
    report = _passing_report()
    report["mandates"] = [{"id": "M1", "status": "unknown"}]
    checks = [orchestrator.CheckResult("pytest", "python3 -m pytest -q", False, error="2 failed")]

    gate = orchestrator.gate_report(
        report,
        mandates,
        checks,
        todo_present=False,
        verifier_status="done",
        verifier_read_only=True,
    )

    assert gate.passed is False
    assert any("check pytest failed" in failure for failure in gate.failures)
    assert any("M1" in failure and "unknown" in failure for failure in gate.failures)


def test_gate_report_fails_weakened_tests_and_verifier_mutation():
    mandates = [orchestrator.Mandate("M1", "required", True)]
    report = _passing_report()
    report["test_integrity"]["weakened"] = True
    checks = [orchestrator.CheckResult("pytest", "python3 -m pytest -q", True)]

    gate = orchestrator.gate_report(
        report,
        mandates,
        checks,
        todo_present=False,
        verifier_status="done",
        verifier_read_only=False,
    )

    assert gate.passed is False
    assert any("weakened tests" in failure for failure in gate.failures)
    assert any("modified existing workspace files" in failure for failure in gate.failures)


def test_gate_report_requires_test_integrity():
    mandates = [orchestrator.Mandate("M1", "required", True)]
    report = _passing_report()
    del report["test_integrity"]
    checks = [orchestrator.CheckResult("pytest", "python3 -m pytest -q", True)]

    gate = orchestrator.gate_report(
        report,
        mandates,
        checks,
        todo_present=False,
        verifier_status="done",
        verifier_read_only=True,
    )

    assert gate.passed is False
    assert any("test_integrity" in failure for failure in gate.failures)


def test_gate_checks_ignores_informational_failures():
    checks = [
        orchestrator.CheckResult("pytest", "python3 -m pytest -q", False, required=True),
        orchestrator.CheckResult("diff_stat", "git diff --stat", False, required=False),
    ]

    gate = orchestrator.gate_checks(checks)

    assert gate.passed is False
    assert any("check pytest failed" in failure for failure in gate.failures)
    assert any("informational check diff_stat failed" in warning for warning in gate.warnings)


def test_default_checks_for_beep_layout(tmp_path):
    (tmp_path / "server.py").write_text("print('server')\n", encoding="utf-8")
    (tmp_path / "beep_locator").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    (tmp_path / "tests" / "detector.test.mjs").write_text("", encoding="utf-8")
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "detector.js").write_text("export {};\n", encoding="utf-8")

    checks = orchestrator.default_checks(tmp_path)
    names = [name for name, _ in checks]

    assert names == ["compileall", "pytest", "node_check", "node_test"]
    assert checks[0][1][-2:] == ["server.py", "beep_locator"]


def test_copy_workspace_excludes_secrets_venv_data_and_backups(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (source / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (source / "secret.pem").write_text("secret\n", encoding="utf-8")
    (source / "venv").mkdir()
    (source / "venv" / "bin").mkdir()
    (source / "venv" / "bin" / "python").write_text("", encoding="utf-8")
    (source / "data").mkdir()
    (source / "data" / "room.json").write_text("{}", encoding="utf-8")
    (source / "tests").mkdir()
    (source / "tests" / "test_app.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (source / "tests" / "test_app.py.bak-20260101").write_text("old\n", encoding="utf-8")

    destination = orchestrator.copy_workspace(source, tmp_path / "copy")

    assert (destination / "app.py").is_file()
    assert (destination / "tests" / "test_app.py").is_file()
    assert not (destination / ".env").exists()
    assert not (destination / "secret.pem").exists()
    assert not (destination / "venv").exists()
    assert not (destination / "data").exists()
    assert not (destination / "tests" / "test_app.py.bak-20260101").exists()


def test_run_check_success_and_failure(tmp_path):
    ok = orchestrator.run_check(
        "ok",
        [sys.executable, "-c", "print('ok')"],
        tmp_path,
        timeout=10,
    )
    failed = orchestrator.run_check(
        "failed",
        [sys.executable, "-c", "raise SystemExit(3)"],
        tmp_path,
        timeout=10,
    )

    assert ok.passed is True
    assert ok.returncode == 0
    assert "ok" in ok.stdout
    assert failed.passed is False
    assert failed.returncode == 3


def test_compare_manifests():
    before = {"a": "1", "b": "2"}
    after = {"a": "3", "c": "4"}

    changed, removed, added = orchestrator.compare_manifests(before, after)

    assert changed == ["a"]
    assert removed == ["b"]
    assert added == ["c"]


def test_build_verifier_prompt_contains_mandates_checks_and_schema():
    mandates = [orchestrator.Mandate("M1", "Serve the UI", True)]
    checks = [orchestrator.CheckResult("pytest", "python3 -m pytest -q", True, stdout="1 passed")]
    git_info = orchestrator.GitInfo(baseline="abc123", status=" M app.py")

    prompt = orchestrator.build_verifier_prompt(
        "1. Serve the UI.",
        mandates,
        git_info,
        checks,
        todo_present=False,
    )

    assert "M1 [required]: Serve the UI" in prompt
    assert "abc123" in prompt
    assert "pytest [PASS, required]" in prompt
    assert "ORIGINAL_PROMPT_BEGIN" in prompt
    assert "MANDATORY INSPECTION PROTOCOL" in prompt
    assert "current file evidence below is authoritative" in prompt
    assert "BASELINE DIFF (inline" in prompt
    assert "CURRENT FILE EVIDENCE" in prompt
    assert "REQUIRED JSON SCHEMA" in prompt
    assert "Return JSON only" in prompt


def test_build_file_evidence_includes_code_and_skips_docs(tmp_path):
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("do not include\n", encoding="utf-8")
    (tmp_path / "TODO.md").write_text("M7: real triangulation later\n", encoding="utf-8")

    evidence = orchestrator.build_file_evidence(
        tmp_path,
        ["app.py", "tests/test_app.py", "notes.md", "TODO.md", "missing.py"],
    )

    assert "--- FILE: app.py ---" in evidence
    assert "VALUE = 1" in evidence
    assert "--- FILE: tests/test_app.py ---" in evidence
    assert "--- FILE: TODO.md ---" in evidence
    assert "M7: real triangulation later" in evidence
    assert "notes.md" not in evidence
    assert "missing.py" not in evidence


def test_scan_async_warnings_flags_unawaited_coroutines():
    checks = [
        orchestrator.CheckResult(
            "pytest",
            "python3 -m pytest -q",
            True,
            stdout="18 passed\nRuntimeWarning: coroutine 'Room.broadcast_message' was never awaited",
        )
    ]

    warning = orchestrator.scan_async_warnings(checks)

    assert warning is not None
    assert warning.name == "unawaited_coroutines"
    assert warning.passed is False
    assert warning.required is True


def test_build_fix_prompt_includes_original_prompt_and_issues():
    prompt = orchestrator.build_fix_prompt("Original mandate", ["M1: still broken"])

    assert "M1: still broken" in prompt
    assert "Original mandate" in prompt


def test_resolve_prompt_supports_prompt_option_and_positional():
    option_args = argparse.Namespace(prompt=[], prompt_text="option prompt", prompt_file=None)
    positional_args = argparse.Namespace(prompt=["positional", "prompt"], prompt_text=None, prompt_file=None)
    both_args = argparse.Namespace(prompt=[], prompt_text="one", prompt_file=Path("x"))

    assert orchestrator._resolve_prompt(option_args) == "option prompt"
    assert orchestrator._resolve_prompt(positional_args) == "positional prompt"
    try:
        orchestrator._resolve_prompt(both_args)
    except SystemExit as exc:
        assert "not both" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def test_collect_git_info_and_test_integrity_detects_added_skip(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test User")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "tests").mkdir()
    test_file = repo / "tests" / "test_app.py"
    test_file.write_text("def test_a():\n    assert 1 == 1\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "initial")
    baseline = _run_git(repo, "rev-parse", "HEAD").stdout.strip()

    test_file.write_text(
        "import pytest\n\n@pytest.mark.skip\ndef test_a():\n    assert 1 == 1\n",
        encoding="utf-8",
    )

    info = orchestrator.collect_git_info(repo, baseline)
    integrity = orchestrator.test_integrity_check(repo, info)
    protected = orchestrator.protected_files_check(info, ["tests/test_app.py"])

    assert info.error == ""
    assert info.baseline == baseline
    assert "tests/test_app.py" in info.changed_files
    assert integrity.passed is False
    assert "pytest.mark.skip" in integrity.stdout
    assert protected.passed is False


def test_run_cycle_runs_implementer_and_verifier_with_fake_agents(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test User")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "initial")
    baseline = _run_git(repo, "rev-parse", "HEAD").stdout.strip()

    calls = []

    def fake_run_agent(prompt, **kwargs):
        calls.append((prompt, Path(kwargs["workspace"])))
        if len(calls) == 1:
            (Path(kwargs["workspace"]) / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            result = {
                "status": "done",
                "run_id": "impl-1",
                "output": "implemented",
                "log_path": "",
                "steps": 1,
            }
        else:
            assert "ORIGINAL_PROMPT_BEGIN" in prompt
            output = json.dumps(
                {
                    "overall": "pass",
                    "mandates": [
                        {"id": "M1", "status": "pass", "evidence": ["app.py:1"], "issues": []}
                    ],
                    "test_integrity": {"weakened": False, "notes": "unchanged"},
                    "unresolved": [],
                }
            )
            result = {
                "status": "done",
                "run_id": "ver-1",
                "output": output,
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
            "--artifacts-dir",
            str(tmp_path / "artifacts"),
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

    assert len(calls) == 2
    assert report["implementer"]["run_id"] == "impl-1"
    assert report["verifier"]["run_id"] == "ver-1"
    assert report["verifier"]["report"]["overall"] == "pass"
    assert report["gate"]["passed"] is True
    assert (repo / "app.py").read_text(encoding="utf-8") == "VALUE = 2\n"


def test_run_tool_count_reads_tool_events(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "DEFAULT_RUN_ROOT", tmp_path)
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "events.jsonl").write_text(
        '{"type": "start"}\n{"type": "tool"}\n{"type": "assistant"}\n{"type": "tool"}\n',
        encoding="utf-8",
    )

    assert orchestrator._run_tool_count("run-1") == 2
    assert orchestrator._run_tool_count("missing") == 0


def test_run_is_finished_reads_finish_event(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "DEFAULT_RUN_ROOT", tmp_path)
    run_id = "20260101-000000-abcdef"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    events = run_dir / "events.jsonl"
    events.write_text(json.dumps({"type": "start"}) + "\n", encoding="utf-8")

    assert orchestrator._run_is_finished(run_id) is False

    with events.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "finish", "status": "done"}) + "\n")

    assert orchestrator._run_is_finished(run_id) is True
    assert orchestrator._run_is_finished("missing") is None
