"""Outer-loop and guardrail tests for the two-agent orchestrator."""

from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

import orchestrator


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test User")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "initial")
    baseline = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, baseline


def _args(tmp_path: Path, repo: Path, *extra: str):
    return orchestrator.build_parser().parse_args(
        [
            "--workspace",
            str(repo),
            "--prompt",
            "1. Keep the app valid.",
            "--artifacts-dir",
            str(tmp_path / "artifacts"),
            "--no-tts-live",
            *extra,
        ]
    )


def _agent_result(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(to_dict=lambda: payload)


def _write_fake_wav(path: Path, payload: bytes = b"voice") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        wav.writeframes(payload)


def _narration_args(tmp_path: Path, *extra: str):
    return orchestrator.build_parser().parse_args(
        [
            "--workspace",
            str(tmp_path),
            "--prompt",
            "1. Keep the app valid.",
            "--artifacts-dir",
            str(tmp_path / "artifacts"),
            *extra,
        ]
    )


def _patch_tts(
    tmp_path: Path,
    monkeypatch,
    queued: list[Path],
    announced: list[tuple[str, dict]] | None = None,
) -> Path:
    from tts import client as tts_client

    public_dir = tmp_path / "public-audio"

    def fake_save(text, filename=None, voice=None, response_format=None, **kwargs):
        target = public_dir / (filename or "speech.wav")
        _write_fake_wav(target, text.encode("utf-8"))
        return {
            "ok": True,
            "path": str(target),
            "url": "/outputs/audio/" + target.name,
            "bytes": target.stat().st_size,
            "voice": voice,
        }

    monkeypatch.setattr(tts_client, "is_enabled", lambda: True)
    monkeypatch.setattr(tts_client, "save_speech", fake_save)
    monkeypatch.setattr(tts_client, "OUTPUT_DIR", public_dir)
    monkeypatch.setattr(orchestrator, "_queue_playback", queued.append)
    if announced is None:
        monkeypatch.setattr(orchestrator, "_announce_handoff", lambda *_args, **_kwargs: None)
    else:
        monkeypatch.setattr(
            orchestrator,
            "_announce_handoff",
            lambda _args, run_id, record, progress=None: announced.append((run_id, record)),
        )
    return public_dir


def _passing_verifier_report() -> dict:
    return {
        "overall": "pass",
        "mandates": [
            {"id": "M1", "status": "pass", "evidence": ["app.py:1"], "issues": []}
        ],
        "test_integrity": {"weakened": False, "notes": "unchanged"},
        "unresolved": [],
    }


def _cycle_report(
    cycle: int,
    passed: bool,
    *,
    failures: list[str] | None = None,
    verifier_report: dict | None = None,
) -> dict:
    return {
        "cycle": cycle,
        "implementer": {
            "status": "done",
            "run_id": f"impl-{cycle}",
            "output": "implemented",
            "log_path": "",
            "steps": 1,
        },
        "git": {
            "baseline": "abc123",
            "status": "",
            "diff_stat": "",
            "changed_files": [],
            "untracked_files": [],
            "test_name_status": [],
            "test_diff": "",
            "diff_patch": "",
            "error": "",
        },
        "checks": [],
        "verifier": {
            "status": "done",
            "run_id": f"ver-{cycle}",
            "read_only": True,
            "report": verifier_report if verifier_report is not None else _passing_verifier_report(),
        },
        "gate": {
            "passed": passed,
            "failures": failures or [],
            "warnings": [],
        },
        "artifacts": "",
    }


def test_orchestrate_stops_after_passing_gate(tmp_path, monkeypatch):
    repo, _ = _init_repo(tmp_path)
    calls = []

    def fake_run_cycle(**kwargs):
        calls.append(kwargs)
        return _cycle_report(kwargs["cycle"], True)

    monkeypatch.setattr(orchestrator, "_run_cycle", fake_run_cycle)
    args = _args(tmp_path, repo, "--max-cycles", "3")

    report = orchestrator.orchestrate(args, "1. Keep the app valid.")

    assert report["overall"] == "pass"
    assert len(calls) == 1
    assert Path(report["orchestration"]["artifacts"], "final-report.json").is_file()


def test_orchestrate_retries_after_failed_gate(tmp_path, monkeypatch):
    repo, _ = _init_repo(tmp_path)
    calls = []

    def fake_run_cycle(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _cycle_report(
                1,
                False,
                failures=["M1: still broken"],
                verifier_report={
                    "overall": "fail",
                    "mandates": [
                        {"id": "M1", "status": "fail", "issues": ["still broken"]}
                    ],
                    "test_integrity": {"weakened": False},
                    "unresolved": ["M1 unresolved"],
                },
            )
        return _cycle_report(2, True)

    monkeypatch.setattr(orchestrator, "_run_cycle", fake_run_cycle)
    args = _args(tmp_path, repo, "--max-cycles", "2")

    report = orchestrator.orchestrate(args, "1. Keep the app valid.")

    assert report["overall"] == "pass"
    assert len(calls) == 2
    assert "M1: still broken" in calls[1]["previous_issues"]
    assert "M1 unresolved" in calls[1]["previous_issues"]


def test_orchestrate_honors_max_cycles(tmp_path, monkeypatch):
    repo, _ = _init_repo(tmp_path)
    calls = []

    def fake_run_cycle(**kwargs):
        calls.append(kwargs)
        return _cycle_report(
            kwargs["cycle"],
            False,
            failures=[f"cycle {kwargs['cycle']} failed"],
        )

    monkeypatch.setattr(orchestrator, "_run_cycle", fake_run_cycle)
    args = _args(tmp_path, repo, "--max-cycles", "2")

    report = orchestrator.orchestrate(args, "1. Keep the app valid.")

    assert report["overall"] == "fail"
    assert len(calls) == 2
    assert report["failures"] == ["cycle 2 failed"]


def test_verify_mode_skips_implementer(tmp_path, monkeypatch):
    repo, _ = _init_repo(tmp_path)
    calls = []

    def fake_run_cycle(**kwargs):
        calls.append(kwargs)
        return _cycle_report(kwargs["cycle"], True)

    monkeypatch.setattr(orchestrator, "_run_cycle", fake_run_cycle)
    args = _args(tmp_path, repo, "--mode", "verify")

    report = orchestrator.orchestrate(args, "1. Keep the app valid.")

    assert report["overall"] == "pass"
    assert len(calls) == 1
    assert calls[0]["run_implementer"] is False
    assert calls[0]["run_verifier"] is True


def test_check_mode_skips_verifier(tmp_path, monkeypatch):
    repo, _ = _init_repo(tmp_path)
    calls = []

    def fake_run_cycle(**kwargs):
        calls.append(kwargs)
        return _cycle_report(kwargs["cycle"], True)

    monkeypatch.setattr(orchestrator, "_run_cycle", fake_run_cycle)
    args = _args(tmp_path, repo, "--mode", "check")

    report = orchestrator.orchestrate(args, "1. Keep the app valid.")

    assert report["overall"] == "pass"
    assert len(calls) == 1
    assert calls[0]["run_implementer"] is False
    assert calls[0]["run_verifier"] is False


def test_verifier_mutation_fails_without_touching_source(tmp_path, monkeypatch):
    repo, baseline = _init_repo(tmp_path)
    verifier_workspaces = []

    def fake_run_agent(prompt, **kwargs):
        workspace = Path(kwargs["workspace"])
        if "ORIGINAL_PROMPT_BEGIN" in prompt:
            verifier_workspaces.append(workspace)
            (workspace / "app.py").write_text("VALUE = 3\n", encoding="utf-8")
            output = json.dumps(_passing_verifier_report())
            return _agent_result(
                {
                    "status": "done",
                    "run_id": "ver-1",
                    "output": output,
                    "log_path": "",
                    "steps": 1,
                }
            )

        (workspace / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        return _agent_result(
            {
                "status": "done",
                "run_id": "impl-1",
                "output": "implemented",
                "log_path": "",
                "steps": 1,
            }
        )

    monkeypatch.setattr(orchestrator, "run_agent", fake_run_agent)
    monkeypatch.setattr(orchestrator, "_run_tool_count", lambda _run_id: 1)
    args = _args(
        tmp_path,
        repo,
        "--check-command",
        "python3 -m py_compile app.py",
    )
    artifact_dir = tmp_path / "artifacts" / "run"

    report = orchestrator._run_cycle(
        cycle=1,
        args=args,
        original_prompt="1. Keep the app valid.",
        mandates=[orchestrator.Mandate("M1", "Keep the app valid.", True)],
        artifact_dir=artifact_dir,
        baseline=baseline,
        run_implementer=True,
        run_verifier=True,
        previous_issues=[],
        progress=lambda _message: None,
    )

    assert report["verifier"]["read_only"] is False
    assert any(
        "verifier modified existing workspace files" in failure
        for failure in report["gate"]["failures"]
    )
    assert (repo / "app.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert verifier_workspaces[0] != repo
    assert (verifier_workspaces[0] / "app.py").read_text(encoding="utf-8") == "VALUE = 3\n"


def test_parse_failure_fails_closed(tmp_path, monkeypatch):
    repo, baseline = _init_repo(tmp_path)

    def fake_run_agent(prompt, **kwargs):
        workspace = Path(kwargs["workspace"])
        if "ORIGINAL_PROMPT_BEGIN" in prompt:
            return _agent_result(
                {
                    "status": "done",
                    "run_id": "ver-1",
                    "output": "not json",
                    "log_path": "",
                    "steps": 1,
                }
            )

        (workspace / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        return _agent_result(
            {
                "status": "done",
                "run_id": "impl-1",
                "output": "implemented",
                "log_path": "",
                "steps": 1,
            }
        )

    monkeypatch.setattr(orchestrator, "run_agent", fake_run_agent)
    monkeypatch.setattr(orchestrator, "_run_tool_count", lambda _run_id: 1)
    args = _args(
        tmp_path,
        repo,
        "--check-command",
        "python3 -m py_compile app.py",
    )
    artifact_dir = tmp_path / "artifacts" / "run"

    report = orchestrator._run_cycle(
        cycle=1,
        args=args,
        original_prompt="1. Keep the app valid.",
        mandates=[orchestrator.Mandate("M1", "Keep the app valid.", True)],
        artifact_dir=artifact_dir,
        baseline=baseline,
        run_implementer=True,
        run_verifier=True,
        previous_issues=[],
        progress=lambda _message: None,
    )

    verifier_report = json.loads(
        (artifact_dir / "cycles" / "cycle-1" / "verifier" / "report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["gate"]["passed"] is False
    assert any(
        "verifier did not return parseable JSON" in failure
        for failure in report["gate"]["failures"]
    )
    assert verifier_report["parse_error"] is True


def test_check_dirty_workspace_rejects_by_default(tmp_path):
    repo, _ = _init_repo(tmp_path)
    (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="uncommitted changes"):
        orchestrator._check_dirty_workspace(repo, allow_dirty=False)

    orchestrator._check_dirty_workspace(repo, allow_dirty=True)


def test_narrate_handoff_writes_role_record_and_queues_playback(tmp_path, monkeypatch):
    queued: list[Path] = []
    announced: list[tuple[str, dict]] = []
    _patch_tts(tmp_path, monkeypatch, queued, announced)
    args = _narration_args(tmp_path, "--tts-local-play")
    artifact_dir = tmp_path / "artifacts" / "run"

    record = orchestrator._narrate_handoff(
        args,
        artifact_dir,
        "reviewer",
        "Verdict: pass.",
        "cycle-01",
        lambda _message: None,
    )

    assert record is not None
    assert record["voice"] == "noa"
    assert record["briefing"].startswith("[noa] Reviewer.")
    target = artifact_dir / "audio" / "cycle-01-reviewer.wav"
    assert target.is_file()
    assert json.loads((artifact_dir / "audio" / "handoff.jsonl").read_text()) == record
    assert queued == [target]
    assert len(announced) == 1
    assert announced[0][0] == "run"
    assert announced[0][1]["role"] == "reviewer"


def test_finalize_handoff_writes_combined_replay_audio(tmp_path, monkeypatch):
    queued: list[Path] = []
    public_dir = _patch_tts(tmp_path, monkeypatch, queued)
    args = _narration_args(tmp_path)
    artifact_dir = tmp_path / "artifacts" / "run"

    orchestrator._narrate_handoff(
        args, artifact_dir, "planner", "Start the run.", "01-planner"
    )
    orchestrator._narrate_handoff(
        args, artifact_dir, "reviewer", "Verdict: pass.", "02-reviewer"
    )
    manifest = orchestrator._finalize_handoff(args, artifact_dir)

    assert manifest is not None
    assert (artifact_dir / "audio" / "handoff.wav").is_file()
    assert (public_dir / f"handoff-{artifact_dir.name}.wav").is_file()
    assert manifest["audio_url"] == f"/outputs/audio/handoff-{artifact_dir.name}.wav"
    assert manifest["replay_url"].endswith(manifest["audio_url"])
    assert [record["voice"] for record in manifest["records"]] == ["lily", "noa"]
    assert manifest["voice_map"]["reviewer"] == "noa"


def test_announce_handoff_posts_segment_to_dashboard(tmp_path, monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data)
        return FakeResponse()

    monkeypatch.setattr(orchestrator.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv(
        "CONTEXTCUT_HANDOFF_ANNOUNCE_URL",
        "http://127.0.0.1:18787/api/tts/announce",
    )
    args = _narration_args(tmp_path)
    record = {
        "step": "cycle-01",
        "role": "reviewer",
        "voice": "noa",
        "url": "/outputs/audio/review.wav",
        "text": "Verdict: pass.",
    }

    orchestrator._announce_handoff(args, "run-1", record)

    assert captured["url"] == "http://127.0.0.1:18787/api/tts/announce"
    assert captured["payload"]["run_id"] == "run-1"
    assert captured["payload"]["url"] == "/outputs/audio/review.wav"


def test_replay_handoff_queues_combined_wav(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "run"
    wav = artifact_dir / "audio" / "handoff.wav"
    _write_fake_wav(wav)
    queued: list[Path] = []
    monkeypatch.setattr(orchestrator, "_queue_playback", lambda path: queued.append(Path(path)))
    monkeypatch.setattr(orchestrator.shutil, "which", lambda _command: "/usr/bin/aplay")

    assert orchestrator._replay_handoff(artifact_dir) == 0
    assert queued == [wav.resolve()]


def test_playback_worker_reports_player_failure(tmp_path, monkeypatch, capsys):
    path = tmp_path / "handoff.wav"
    path.write_bytes(b"fake")
    result = SimpleNamespace(returncode=1, stderr="Device or resource busy", stdout="")
    monkeypatch.setattr(orchestrator.shutil, "which", lambda _command: "/usr/bin/aplay")
    monkeypatch.setattr(orchestrator.subprocess, "run", lambda *_args, **_kwargs: result)

    while not orchestrator._PLAYBACK_QUEUE.empty():
        orchestrator._PLAYBACK_QUEUE.get_nowait()
        orchestrator._PLAYBACK_QUEUE.task_done()
    orchestrator._PLAYBACK_QUEUE.put(path)
    orchestrator._PLAYBACK_QUEUE.put(None)
    orchestrator._playback_worker()

    assert "Device or resource busy" in capsys.readouterr().err


def test_no_tts_live_skips_narration(tmp_path, monkeypatch):
    def fail_save(*_args, **_kwargs):
        raise AssertionError("save_speech should not be called")

    monkeypatch.setattr("tts.client.save_speech", fail_save)
    args = orchestrator.build_parser().parse_args(
        [
            "--workspace",
            str(tmp_path),
            "--prompt",
            "1. Keep the app valid.",
            "--no-tts-live",
        ]
    )
    artifact_dir = tmp_path / "artifacts" / "run"

    assert (
        orchestrator._narrate_handoff(
            args, artifact_dir, "planner", "Start", "01-planner"
        )
        is None
    )
    assert not (artifact_dir / "audio").exists()
