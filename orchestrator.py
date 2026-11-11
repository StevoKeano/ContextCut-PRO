"""Two-agent orchestration for the headless coding worker.

The orchestrator runs an implementer, freezes the result, executes deterministic
checks, then starts a separate verifier agent in a disposable workspace copy.
The verifier must return a JSON verdict covering every mandate in the original
prompt. The orchestrator owns the gate and never trusts the implementer's
summary.

Examples:
    python3 orchestrator.py --workspace ~/dev/project --prompt-file task.txt \
        --implementer-model qwen3-coder:30b --verifier-model qwen3:14b-q8_0

    python3 orchestrator.py --mode verify --workspace ~/dev/project \
        --prompt-file task.txt --baseline b965be6 \
        --implementer-run-id 20261111-150819-71536f
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

DEFAULT_ARTIFACT_ROOT = Path.home() / ".contextcut" / "orchestrations"
DEFAULT_RUN_ROOT = Path.home() / ".contextcut" / "coding_runs"
DEFAULT_CTX_LIMIT = 32768
DEFAULT_IMPLEMENTER_STEPS = 24
DEFAULT_VERIFIER_STEPS = 12
DEFAULT_IMPLEMENTER_TIMEOUT = 1800.0
DEFAULT_VERIFIER_TIMEOUT = 900.0
DEFAULT_MAX_TOKENS = 16384
DEFAULT_VERIFIER_MAX_TOKENS = 8192
DEFAULT_CHECK_TIMEOUT = 300
MAX_REPORT_CHARS = 12000

IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".orchestrator",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "__pycache__",
    "build",
    "data",
    "dist",
    "env",
    "node_modules",
    "venv",
    ".venv",
}
IGNORE_SUFFIXES = (".pyc", ".pyo", ".log", ".pid", ".tmp")
SECRET_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".pgpass",
    ".htpasswd",
    "credentials",
    "secrets",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
}
SECRET_PREFIXES = (".env.",)
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".crt")

FORBIDDEN_TEST_PATTERNS = (
    ("pytest.mark.skip", re.compile(r"pytest\.mark\.skip", re.IGNORECASE)),
    ("pytest.skip", re.compile(r"pytest\.skip\b", re.IGNORECASE)),
    ("unittest.skip", re.compile(r"unittest\.skip", re.IGNORECASE)),
    ("xfail", re.compile(r"\bxfail\b", re.IGNORECASE)),
    ("assert True", re.compile(r"\bassert\s+True\b")),
    ("assert 1 == 1", re.compile(r"\bassert\s+1\s*==\s*1\b")),
)

OPTIONAL_SECTION_RE = re.compile(r"^\s*(?:ONLY\s+IF|OPTIONAL)\b", re.IGNORECASE)
NUMBERED_RE = re.compile(r"^\s*(\d+)\.\s*(.*)$")
HEADING_RE = re.compile(r"^[A-Z][A-Z0-9 /&_-]{2,}:?\s*$")
SUBBULLET_RE = re.compile(r"^\s{2,}[-*]\s+")


@dataclass
class Mandate:
    id: str
    text: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "required": self.required}


@dataclass
class CheckResult:
    name: str
    command: str
    passed: bool
    required: bool = True
    returncode: int | None = None
    duration_s: float = 0.0
    stdout: str = ""
    stderr: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "passed": self.passed,
            "required": self.required,
            "returncode": self.returncode,
            "duration_s": round(self.duration_s, 3),
            "stdout": _clip_text(self.stdout),
            "stderr": _clip_text(self.stderr),
            "error": self.error,
        }


@dataclass
class GitInfo:
    root: str = ""
    baseline: str = ""
    status: str = ""
    diff_stat: str = ""
    changed_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    test_name_status: list[str] = field(default_factory=list)
    test_diff: str = ""
    diff_patch: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "baseline": self.baseline,
            "status": self.status,
            "diff_stat": self.diff_stat,
            "changed_files": self.changed_files,
            "untracked_files": self.untracked_files,
            "test_name_status": self.test_name_status,
            "error": self.error,
        }


@dataclass
class GateResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failures": self.failures,
            "warnings": self.warnings,
        }


def _clip_text(text: str, limit: int = MAX_REPORT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[truncated {len(text) - limit} chars]"


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, data: Any) -> None:
    _write_text(path, json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_mandates(prompt: str) -> list[Mandate]:
    mandates: list[Mandate] = []
    current: Mandate | None = None
    required = True

    def flush() -> None:
        nonlocal current
        if current is not None and current.text.strip():
            mandates.append(current)
        current = None

    for line in prompt.splitlines():
        if OPTIONAL_SECTION_RE.match(line):
            flush()
            required = False
            continue

        match = NUMBERED_RE.match(line)
        if match:
            flush()
            current = Mandate(
                id=f"M{len(mandates) + 1}",
                text=match.group(2).strip(),
                required=required,
            )
            continue

        if current is None:
            continue

        stripped = line.strip()
        if not stripped:
            continue

        if HEADING_RE.match(stripped):
            flush()
            continue

        if SUBBULLET_RE.match(line) or line.startswith((" ", "\t")):
            current.text = f"{current.text} {stripped}".strip()
        else:
            flush()

    flush()

    if not mandates:
        mandates = [Mandate(id="M1", text=prompt.strip(), required=True)]

    for index, mandate in enumerate(mandates, 1):
        mandate.id = f"M{index}"
    return mandates


def load_mandates(path: Path) -> list[Mandate]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("mandates")
    if not isinstance(data, list):
        raise ValueError("mandates file must contain a list or an object with a mandates list")

    mandates: list[Mandate] = []
    for index, item in enumerate(data, 1):
        if isinstance(item, str):
            mandates.append(Mandate(id=f"M{index}", text=item, required=True))
            continue
        if not isinstance(item, dict):
            raise ValueError(f"mandate {index} must be a string or object")
        text = str(item.get("text", "")).strip()
        if not text:
            raise ValueError(f"mandate {index} is missing text")
        mandates.append(
            Mandate(
                id=str(item.get("id") or f"M{index}"),
                text=text,
                required=_as_bool(item.get("required", True), default=True),
            )
        )

    ids = [m.id for m in mandates]
    if len(ids) != len(set(ids)):
        raise ValueError("mandate ids must be unique")
    return mandates


def _run_process(
    cmd: Sequence[str],
    cwd: Path,
    timeout: float,
) -> tuple[str, int | None, str, str, str, float]:
    command = shlex.join([str(part) for part in cmd])
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [str(part) for part in cmd],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return command, proc.returncode, proc.stdout or "", proc.stderr or "", "", time.monotonic() - started
    except FileNotFoundError as exc:
        return command, None, "", "", str(exc), time.monotonic() - started
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return command, None, stdout, stderr, f"timeout after {timeout:g}s", time.monotonic() - started
    except Exception as exc:
        return command, None, "", "", str(exc), time.monotonic() - started


def run_check(
    name: str,
    cmd: Sequence[str],
    cwd: Path,
    timeout: float,
    required: bool = True,
) -> CheckResult:
    command, returncode, stdout, stderr, error, duration = _run_process(cmd, cwd, timeout)
    passed = returncode == 0 and not error
    return CheckResult(
        name=name,
        command=command,
        passed=passed,
        required=required,
        returncode=returncode,
        duration_s=duration,
        stdout=stdout,
        stderr=stderr,
        error=error,
    )


def _git(workspace: Path, args: Sequence[str]) -> tuple[int, str, str, str]:
    command, returncode, stdout, stderr, error, _ = _run_process(
        ["git", *args], workspace, 60
    )
    return returncode if returncode is not None else 1, stdout, stderr, error


def collect_git_info(workspace: Path, baseline: str | None = None) -> GitInfo:
    workspace = Path(workspace).expanduser().resolve()
    returncode, stdout, stderr, error = _git(workspace, ["rev-parse", "--show-toplevel"])
    if returncode != 0:
        return GitInfo(error=stderr.strip() or error or "not a git repository")

    root = stdout.strip()
    base = (baseline or "").strip()
    if not base:
        returncode, stdout, stderr, error = _git(workspace, ["rev-parse", "HEAD"])
        if returncode != 0:
            return GitInfo(root=root, error=stderr.strip() or error or "cannot resolve HEAD")
        base = stdout.strip()

    returncode, _, stderr, error = _git(workspace, ["rev-parse", "--verify", base])
    if returncode != 0:
        return GitInfo(
            root=root,
            baseline=base,
            error=stderr.strip() or error or f"invalid baseline: {base}",
        )

    status_rc, status_out, _, _ = _git(workspace, ["status", "--porcelain"])
    diff_stat_rc, diff_stat_out, _, _ = _git(
        workspace, ["diff", "--stat", base, "--", "."]
    )
    changed_rc, changed_out, _, _ = _git(
        workspace, ["diff", "--name-only", base, "--", "."]
    )
    untracked_rc, untracked_out, _, _ = _git(
        workspace, ["ls-files", "--others", "--exclude-standard", "--", "."]
    )
    test_status_rc, test_status_out, _, _ = _git(
        workspace, ["diff", "--name-status", base, "--", "tests"]
    )
    test_diff_rc, test_diff_out, _, _ = _git(
        workspace, ["diff", "--unified=0", base, "--", "tests"]
    )
    patch_rc, patch_out, _, _ = _git(
        workspace, ["diff", "--binary", base, "--", "."]
    )

    errors = []
    if status_rc != 0:
        errors.append("git status failed")
    if diff_stat_rc != 0:
        errors.append("git diff --stat failed")
    if changed_rc != 0:
        errors.append("git diff --name-only failed")
    if untracked_rc != 0:
        errors.append("git ls-files failed")
    if test_status_rc != 0:
        errors.append("git diff --name-status tests failed")
    if test_diff_rc != 0:
        errors.append("git diff tests failed")
    if patch_rc != 0:
        errors.append("git diff patch failed")

    return GitInfo(
        root=root,
        baseline=base,
        status=status_out,
        diff_stat=diff_stat_out,
        changed_files=[line for line in changed_out.splitlines() if line.strip()],
        untracked_files=[line for line in untracked_out.splitlines() if line.strip()],
        test_name_status=[line for line in test_status_out.splitlines() if line.strip()],
        test_diff=test_diff_out,
        diff_patch=patch_out,
        error="; ".join(errors),
    )


def test_integrity_check(workspace: Path, git_info: GitInfo) -> CheckResult:
    if git_info.error:
        return CheckResult(
            name="test_integrity",
            command="git diff inspection",
            passed=True,
            required=False,
            stdout="Skipped because git baseline information is unavailable.",
            error=git_info.error,
        )

    issues: list[str] = []
    warnings: list[str] = []
    changed_tests: set[str] = set()

    for line in git_info.test_name_status:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0], parts[1]
        changed_tests.add(path)
        if status.startswith("D"):
            issues.append(f"deleted test file: {path}")

    for rel in git_info.untracked_files:
        if rel.startswith("tests/") and rel.endswith(".py"):
            changed_tests.add(rel)

    for line in git_info.test_diff.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            added = line[1:]
            for label, pattern in FORBIDDEN_TEST_PATTERNS:
                if pattern.search(added):
                    issues.append(f"added {label}: {added.strip()[:160]}")
        elif line.startswith("-"):
            removed = line[1:]
            if re.match(r"^\s*(?:async\s+)?def test_", removed):
                issues.append(f"removed test function: {removed.strip()[:160]}")
            elif re.search(r"\bassert\b", removed):
                warnings.append(f"removed assertion: {removed.strip()[:160]}")

    for rel in sorted(changed_tests):
        if not rel.startswith("tests/") or not rel.endswith(".py"):
            continue
        path = Path(workspace) / rel
        if not path.is_file():
            continue
        if rel in git_info.untracked_files:
            for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for label, pattern in FORBIDDEN_TEST_PATTERNS:
                    if pattern.search(line):
                        issues.append(f"{rel}:{lineno}: {label}")

    if changed_tests:
        warnings.append("changed test files: " + ", ".join(sorted(changed_tests)))

    lines = [f"FAIL: {issue}" for issue in issues]
    lines.extend(f"WARN: {warning}" for warning in warnings)
    return CheckResult(
        name="test_integrity",
        command="git diff inspection",
        passed=not issues,
        required=True,
        stdout="\n".join(lines),
        error="" if not issues else "test integrity violations detected",
    )


def protected_files_check(git_info: GitInfo, protected: Sequence[str]) -> CheckResult:
    if git_info.error:
        return CheckResult(
            name="protected_files",
            command="git diff inspection",
            passed=True,
            required=False,
            stdout="Skipped because git baseline information is unavailable.",
            error=git_info.error,
        )

    changed = set(git_info.changed_files) | set(git_info.untracked_files)
    hits: list[str] = []
    for raw in protected:
        path = raw.strip().lstrip("./")
        if not path:
            continue
        prefix = path.rstrip("/") + "/"
        if path in changed or any(item.startswith(prefix) for item in changed):
            hits.append(path)

    return CheckResult(
        name="protected_files",
        command="git diff inspection",
        passed=not hits,
        required=True,
        stdout="\n".join(f"changed protected file: {path}" for path in hits),
        error="" if not hits else "protected files changed",
    )


def default_checks(workspace: Path) -> list[tuple[str, list[str]]]:
    workspace = Path(workspace)
    checks: list[tuple[str, list[str]]] = []

    python_targets = []
    if (workspace / "server.py").is_file():
        python_targets.append("server.py")
    if (workspace / "beep_locator").is_dir():
        python_targets.append("beep_locator")
    if python_targets:
        checks.append(("compileall", ["python3", "-m", "compileall", "-q", *python_targets]))

    tests_dir = workspace / "tests"
    if tests_dir.is_dir() and any(tests_dir.rglob("test_*.py")):
        checks.append(("pytest", ["python3", "-m", "pytest", "-q"]))

    if (workspace / "static" / "detector.js").is_file():
        checks.append(("node_check", ["node", "--check", "static/detector.js"]))

    if (workspace / "tests" / "detector.test.mjs").is_file():
        checks.append(("node_test", ["node", "--test", "tests/detector.test.mjs"]))

    return checks


def scan_async_warnings(checks: Sequence[CheckResult]) -> CheckResult | None:
    pytest_result = next((check for check in checks if check.name == "pytest"), None)
    if pytest_result is None:
        return None
    combined = f"{pytest_result.stdout}\n{pytest_result.stderr}"
    if "never awaited" not in combined:
        return None
    lines = [line for line in combined.splitlines() if "never awaited" in line or "app.py:" in line]
    return CheckResult(
        name="unawaited_coroutines",
        command="pytest output scan",
        passed=False,
        required=True,
        stdout="\n".join(lines[:20]),
        error="pytest reported un-awaited coroutines",
    )


def run_deterministic_checks(
    source_workspace: Path,
    check_workspace: Path,
    git_info: GitInfo,
    protected: Sequence[str],
    custom_commands: Sequence[tuple[str, list[str]]],
    timeout: float,
) -> list[CheckResult]:
    results: list[CheckResult] = []

    if git_info.error:
        results.append(
            CheckResult(
                name="git_baseline",
                command="git rev-parse",
                passed=True,
                required=False,
                stdout="Git-based checks skipped.",
                error=git_info.error,
            )
        )
    else:
        results.append(test_integrity_check(source_workspace, git_info))
        if protected:
            results.append(protected_files_check(git_info, protected))
        results.append(
            CheckResult(
                name="diff_stat",
                command="git diff --stat",
                passed=True,
                required=False,
                stdout=git_info.diff_stat,
            )
        )
        results.append(
            CheckResult(
                name="git_status",
                command="git status --porcelain",
                passed=True,
                required=False,
                stdout=git_info.status,
            )
        )
        if git_info.untracked_files:
            results.append(
                CheckResult(
                    name="untracked_files",
                    command="git ls-files --others --exclude-standard",
                    passed=True,
                    required=False,
                    stdout="\n".join(git_info.untracked_files),
                )
            )

    commands = list(custom_commands) if custom_commands else default_checks(check_workspace)
    if not commands:
        results.append(
            CheckResult(
                name="checks_configured",
                command="internal",
                passed=False,
                required=True,
                error="no checks found; pass --check-command",
            )
        )

    for index, (name, cmd) in enumerate(commands, 1):
        results.append(run_check(name or f"check-{index}", cmd, check_workspace, timeout))

    async_warning = scan_async_warnings(results)
    if async_warning is not None:
        results.append(async_warning)

    return results


def _ignore_copy(_directory: str, names: list[str]) -> list[str]:
    ignored: list[str] = []
    for name in names:
        if name in IGNORE_DIRS or name in SECRET_NAMES:
            ignored.append(name)
        elif name.startswith(SECRET_PREFIXES) or name.endswith(SECRET_SUFFIXES):
            ignored.append(name)
        elif name.endswith(IGNORE_SUFFIXES) or ".bak-" in name:
            ignored.append(name)
    return ignored


def copy_workspace(source: Path, destination: Path) -> Path:
    source = Path(source).expanduser().resolve()
    destination = Path(destination)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=_ignore_copy)
    return destination


def _manifest_ignored(rel: Path) -> bool:
    if any(part in IGNORE_DIRS for part in rel.parts[:-1]):
        return True
    name = rel.name
    if name in SECRET_NAMES:
        return True
    if name.startswith(SECRET_PREFIXES) or name.endswith(SECRET_SUFFIXES):
        return True
    if name.endswith(IGNORE_SUFFIXES) or ".bak-" in name:
        return True
    return False


def file_manifest(root: Path) -> dict[str, str]:
    root = Path(root)
    manifest: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _manifest_ignored(rel):
            continue
        manifest[rel.as_posix()] = _sha256(path)
    return manifest


def compare_manifests(
    before: dict[str, str], after: dict[str, str]
) -> tuple[list[str], list[str], list[str]]:
    changed = sorted(key for key in before.keys() & after.keys() if before[key] != after[key])
    removed = sorted(before.keys() - after.keys())
    added = sorted(after.keys() - before.keys())
    return changed, removed, added


def _format_mandates(mandates: Sequence[Mandate]) -> str:
    lines = []
    for mandate in mandates:
        kind = "required" if mandate.required else "optional"
        lines.append(f"- {mandate.id} [{kind}]: {mandate.text}")
    return "\n".join(lines)


def _format_checks(checks: Sequence[CheckResult]) -> str:
    lines: list[str] = []
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        kind = "required" if check.required else "informational"
        lines.append(f"- {check.name} [{status}, {kind}]: {check.command}")
        if check.error:
            lines.append(f"  error: {check.error}")
        if check.stdout.strip():
            lines.append("  stdout:")
            lines.append(_indent(_clip_text(check.stdout, 4000)))
        if check.stderr.strip():
            lines.append("  stderr:")
            lines.append(_indent(_clip_text(check.stderr, 4000)))
    return "\n".join(lines)


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def build_file_evidence(
    workspace: Path,
    paths: Sequence[str],
    *,
    max_file_chars: int = 12000,
    max_total_chars: int = 60000,
) -> str:
    parts: list[str] = []
    total = 0
    seen: set[str] = set()
    skipped_suffixes = {".md", ".png", ".jpg", ".jpeg", ".gif", ".wav", ".pyc"}
    for raw in paths:
        if not raw or raw in seen:
            continue
        seen.add(raw)
        if raw.startswith((".orchestrator/", "data/")):
            continue
        if Path(raw).suffix.lower() in skipped_suffixes and Path(raw).name != "TODO.md":
            continue
        path = workspace / raw
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        block = f"--- FILE: {raw} ---\n{_clip_text(text, max_file_chars)}\n"
        if total + len(block) > max_total_chars:
            remaining = max_total_chars - total
            if remaining <= 200:
                break
            block = block[:remaining] + "\n... [file evidence truncated]\n"
        parts.append(block)
        total += len(block)
        if total >= max_total_chars:
            break
    return "\n".join(parts) if parts else "(no file evidence available)"


def build_verifier_prompt(
    original_prompt: str,
    mandates: Sequence[Mandate],
    git_info: GitInfo,
    checks: Sequence[CheckResult],
    todo_present: bool,
    file_evidence: str = "",
) -> str:
    return f"""You are an independent verifier. Do not edit existing project files.
The workspace is a disposable copy. If you need scratch files, put them under
.orchestrator/scratch/.

You must independently verify every mandate below. Do not trust any implementer
summary; none is provided. Read the code, run the required commands, and check
the actual behavior.

MANDATORY INSPECTION PROTOCOL
The current file evidence below is authoritative and was read from the
verification workspace. Base your verdict on it, not on the original prompt.
The original prompt describes the starting state, not necessarily the current
state. When reading the baseline diff, lines beginning with '-' are removed code
and lines beginning with '+' are current code. Do not treat removed lines as present.
You have tools. Use them when the embedded evidence is insufficient or when you
need to verify runtime behavior. If you use tools, inspect the actual current
files rather than inferring from the prompt. A report that contradicts the
current file evidence is invalid.

MANDATE CHECKLIST
{_format_mandates(mandates)}

ORIGINAL PROMPT
<<<ORIGINAL_PROMPT_BEGIN>>>
{original_prompt.strip()}
<<<ORIGINAL_PROMPT_END>>>

BASELINE
- baseline: {git_info.baseline or "unavailable"}
- status:
{_indent(git_info.status or "(clean or unavailable)")}
- diff stat:
{_indent(git_info.diff_stat or "(no diff or unavailable)")}
- baseline diff: .orchestrator/implementer.diff
- git status: .orchestrator/git-status.txt
- diff stat: .orchestrator/diff-stat.txt

BASELINE DIFF (inline, clipped; '-' removed, '+' current)
{_clip_text(git_info.diff_patch or "(no diff or unavailable)", 12000)}

CURRENT FILE EVIDENCE (authoritative; read from the verification workspace)
{file_evidence or "(no file evidence available)"}

DETERMINISTIC CHECK RESULTS
{_format_checks(checks)}

TODO.md PRESENT: {todo_present}

VERIFICATION RULES
1. A required mandate must be PASS. Anything else fails the gate.
2. An optional mandate may be PASS, or DEFERRED only if TODO.md exists and
   actually covers it. FAIL and UNKNOWN fail the gate.
3. UNKNOWN means you could not establish the result; it fails closed.
4. Re-run the key commands yourself. Do not rely only on the provided results.
5. Check that tests were not deleted, skipped, xfailed, trivialized, or weakened.
   Compare test files against .orchestrator/implementer.diff.
6. Check that no placeholder or simulated implementation remains where the
   mandate requires real behavior.
7. Evidence must name files, line numbers, commands, and observed output.
8. Return JSON only. Do not use markdown fences or add prose outside the JSON.

REQUIRED JSON SCHEMA
{{
  "overall": "pass" or "fail",
  "mandates": [
    {{
      "id": "M1",
      "status": "pass" or "fail" or "unknown" or "deferred",
      "evidence": ["file:line ...", "command ..."],
      "issues": ["specific unresolved problem"]
    }}
  ],
  "test_integrity": {{
    "weakened": false,
    "notes": "what you checked"
  }},
  "unresolved": ["mandate ids or issue summaries"]
}}
"""


def parse_verifier_report(text: str) -> dict[str, Any] | None:
    if not text or not text.strip():
        return None

    candidates: list[str] = []
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.append(fenced.group(1))
    candidates.append(text)

    for candidate in candidates:
        start = candidate.find("{")
        while start != -1:
            try:
                obj, _ = json.JSONDecoder().raw_decode(candidate[start:])
            except json.JSONDecodeError:
                start = candidate.find("{", start + 1)
                continue
            if isinstance(obj, dict) and ("mandates" in obj or "overall" in obj):
                return obj
            start = candidate.find("{", start + 1)
    return None


def _normalize_status(value: Any) -> str:
    return str(value or "").strip().lower()


def _status_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = report.get("mandates")
    result: dict[str, dict[str, Any]] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            mandate_id = str(item.get("id") or "").strip()
            if mandate_id:
                result[mandate_id] = item
    elif isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                item = dict(value)
            else:
                item = {"status": value}
            item.setdefault("id", key)
            result[str(key)] = item
    return result


def _report_issues(report: dict[str, Any] | None) -> list[str]:
    if not report:
        return []
    issues: list[str] = []
    for item in _status_map(report).values():
        raw = item.get("issues") or []
        if isinstance(raw, str):
            raw = [raw]
        if isinstance(raw, list):
            for issue in raw:
                issues.append(f"{item.get('id', '?')}: {issue}")
    unresolved = report.get("unresolved") or []
    if isinstance(unresolved, str):
        unresolved = [unresolved]
    if isinstance(unresolved, list):
        issues.extend(str(item) for item in unresolved)
    return issues


def gate_report(
    report: dict[str, Any] | None,
    mandates: Sequence[Mandate],
    checks: Sequence[CheckResult],
    *,
    todo_present: bool,
    verifier_status: str,
    verifier_read_only: bool,
) -> GateResult:
    failures: list[str] = []
    warnings: list[str] = []

    for check in checks:
        if check.required and not check.passed:
            detail = check.error or check.stderr or check.stdout
            failures.append(f"check {check.name} failed: {_clip_text(detail, 800).strip()}")
        elif not check.passed:
            detail = check.error or check.stderr or check.stdout
            warnings.append(f"informational check {check.name} failed: {_clip_text(detail, 400).strip()}")

    if verifier_status != "done":
        failures.append(f"verifier stopped with status={verifier_status}")
    if not verifier_read_only:
        failures.append("verifier modified existing workspace files")

    if report is None:
        failures.append("verifier did not return parseable JSON")
    else:
        overall = _normalize_status(report.get("overall"))
        if overall not in {"pass", "fail"}:
            failures.append("verifier report is missing overall=pass or overall=fail")
        elif overall == "fail":
            failures.append("verifier overall=fail")

        integrity = report.get("test_integrity")
        if not isinstance(integrity, dict):
            failures.append("verifier report is missing test_integrity")
        elif _as_bool(integrity.get("weakened"), default=False):
            failures.append("verifier reports weakened tests")

        unresolved = report.get("unresolved") or []
        if isinstance(unresolved, str):
            unresolved = [unresolved]
        if unresolved:
            failures.append("verifier unresolved: " + "; ".join(str(item) for item in unresolved))

        statuses = _status_map(report)
        for mandate in mandates:
            item = statuses.get(mandate.id)
            if item is None:
                failures.append(f"{mandate.id}: verifier returned no verdict")
                continue
            status = _normalize_status(item.get("status"))
            if mandate.required:
                if status != "pass":
                    failures.append(f"{mandate.id}: required mandate status={status or 'missing'}")
            elif status == "pass":
                continue
            elif status == "deferred":
                if not todo_present:
                    failures.append(f"{mandate.id}: deferred but TODO.md is missing")
            else:
                failures.append(f"{mandate.id}: optional mandate status={status or 'missing'}")

        expected = {mandate.id for mandate in mandates}
        extra = sorted(set(statuses) - expected)
        if extra:
            warnings.append("verifier returned unknown mandate ids: " + ", ".join(extra))

    return GateResult(
        passed=not failures,
        failures=_unique(failures),
        warnings=_unique(warnings),
    )


def gate_checks(checks: Sequence[CheckResult]) -> GateResult:
    failures: list[str] = []
    warnings: list[str] = []
    for check in checks:
        if check.required and not check.passed:
            detail = check.error or check.stderr or check.stdout
            failures.append(f"check {check.name} failed: {_clip_text(detail, 800).strip()}")
        elif not check.passed:
            detail = check.error or check.stderr or check.stdout
            warnings.append(f"informational check {check.name} failed: {_clip_text(detail, 400).strip()}")
    return GateResult(passed=not failures, failures=_unique(failures), warnings=_unique(warnings))


def run_agent(
    prompt: str,
    *,
    workspace: Path,
    model: str | None,
    base_url: str | None,
    api_key: str | None,
    max_steps: int,
    timeout: float,
    reasoning: str,
    max_tokens: int,
    ctx_limit: int,
    progress: Callable[[str], None],
) -> Any:
    from coding_agent import run_task

    return run_task(
        prompt,
        workspace=workspace,
        model=model,
        base_url=base_url,
        api_key=api_key,
        max_steps=max_steps,
        timeout=timeout,
        reasoning=reasoning,
        max_tokens=max_tokens,
        ctx_limit=ctx_limit,
        progress=progress,
    )


def _agent_result_dict(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, dict):
        return result
    return {"status": "error", "output": str(result), "run_id": "", "log_path": ""}


def _copy_run_log(result: dict[str, Any], destination: Path) -> None:
    log_path = str(result.get("log_path") or "")
    if not log_path:
        return
    source = Path(log_path).expanduser()
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _write_git_artifacts(cycle_dir: Path, git_info: GitInfo) -> None:
    git_dir = cycle_dir / "git"
    git_dir.mkdir(parents=True, exist_ok=True)
    _write_text(git_dir / "baseline.txt", (git_info.baseline or "") + "\n")
    _write_text(git_dir / "status.txt", git_info.status or "")
    _write_text(git_dir / "diff-stat.txt", git_info.diff_stat or "")
    _write_text(git_dir / "diff.patch", git_info.diff_patch or "")
    _write_text(git_dir / "test.diff", git_info.test_diff or "")
    if git_info.error:
        _write_text(git_dir / "error.txt", git_info.error + "\n")


def _write_verifier_context(verifier_dir: Path, git_info: GitInfo) -> None:
    context_dir = verifier_dir / ".orchestrator"
    context_dir.mkdir(parents=True, exist_ok=True)
    _write_text(context_dir / "baseline.txt", (git_info.baseline or "") + "\n")
    _write_text(context_dir / "git-status.txt", git_info.status or "")
    _write_text(context_dir / "diff-stat.txt", git_info.diff_stat or "")
    _write_text(context_dir / "implementer.diff", git_info.diff_patch or "")
    _write_text(context_dir / "test.diff", git_info.test_diff or "")


def _save_checks(cycle_dir: Path, checks: Sequence[CheckResult]) -> None:
    check_dir = cycle_dir / "checks"
    check_dir.mkdir(parents=True, exist_ok=True)
    for index, check in enumerate(checks, 1):
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", check.name).strip("-") or f"check-{index}"
        _write_text(check_dir / f"{index:02d}-{safe}.stdout.txt", check.stdout or "")
        _write_text(check_dir / f"{index:02d}-{safe}.stderr.txt", check.stderr or "")
    _write_json(check_dir / "checks.json", [check.to_dict() for check in checks])


def build_fix_prompt(original_prompt: str, issues: Sequence[str]) -> str:
    bullets = "\n".join(f"- {issue}" for issue in issues) or "- No details were returned."
    return f"""The previous verification found these unresolved issues:
{bullets}

Fix only these gaps. Do not weaken tests. Preserve all completed work.

ORIGINAL MANDATE
{original_prompt.strip()}
"""


def _run_is_finished(run_id: str) -> bool | None:
    events_path = DEFAULT_RUN_ROOT / run_id / "events.jsonl"
    if not events_path.is_file():
        return None
    try:
        for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("type") == "finish":
                return True
    except (OSError, json.JSONDecodeError):
        return None
    return False


def _run_tool_count(run_id: str) -> int:
    events_path = DEFAULT_RUN_ROOT / run_id / "events.jsonl"
    if not events_path.is_file():
        return 0
    count = 0
    try:
        for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("type") == "tool":
                count += 1
    except (OSError, json.JSONDecodeError):
        return 0
    return count


def _run_cycle(
    *,
    cycle: int,
    args: argparse.Namespace,
    original_prompt: str,
    mandates: Sequence[Mandate],
    artifact_dir: Path,
    baseline: str | None,
    run_implementer: bool,
    run_verifier: bool,
    previous_issues: Sequence[str],
    progress: Callable[[str], None],
) -> dict[str, Any]:
    cycle_dir = artifact_dir / "cycles" / f"cycle-{cycle}"
    cycle_dir.mkdir(parents=True, exist_ok=True)
    source = Path(args.workspace).expanduser().resolve()

    implementer: dict[str, Any]
    if run_implementer:
        prompt = original_prompt if cycle == 1 else build_fix_prompt(original_prompt, previous_issues)
        _write_text(cycle_dir / "implementer" / "prompt.txt", prompt)
        progress(f"[cycle {cycle}] implementer start")
        try:
            result = run_agent(
                prompt,
                workspace=source,
                model=args.implementer_model,
                base_url=args.base_url,
                api_key=args.api_key,
                max_steps=args.implementer_max_steps,
                timeout=args.implementer_timeout,
                reasoning=args.reasoning,
                max_tokens=args.max_tokens,
                ctx_limit=args.ctx_limit,
                progress=progress,
            )
            implementer = _agent_result_dict(result)
        except Exception as exc:
            implementer = {"status": "error", "output": str(exc), "run_id": "", "log_path": ""}
        _write_json(cycle_dir / "implementer" / "result.json", implementer)
        _copy_run_log(implementer, cycle_dir / "implementer" / "events.jsonl")
        progress(
            f"[cycle {cycle}] implementer {implementer.get('status')} "
            f"run={implementer.get('run_id')} steps={implementer.get('steps')}"
        )
    else:
        implementer = {
            "status": "not-run",
            "run_id": args.implementer_run_id or "",
            "output": "Existing workspace verified without running an implementer.",
            "log_path": "",
        }
        _write_json(cycle_dir / "implementer" / "result.json", implementer)

    git_info = collect_git_info(source, baseline)
    _write_git_artifacts(cycle_dir, git_info)
    if git_info.error:
        progress(f"[cycle {cycle}] git: {git_info.error}")

    check_workspace = copy_workspace(source, cycle_dir / "check-workspace")
    custom_commands = [
        (f"custom-{index}", shlex.split(command))
        for index, command in enumerate(args.check_command, 1)
        if command.strip()
    ]
    checks = run_deterministic_checks(
        source,
        check_workspace,
        git_info,
        args.protected,
        custom_commands,
        args.check_timeout,
    )
    _save_checks(cycle_dir, checks)
    progress(f"[cycle {cycle}] deterministic checks: {sum(1 for c in checks if not c.passed)} failed")

    verifier: dict[str, Any]
    verifier_report: dict[str, Any] | None = None
    verifier_read_only = True
    verifier_status = "not-run"
    gate: GateResult

    if run_verifier:
        verifier_dir = copy_workspace(source, cycle_dir / "verifier-workspace")
        _write_verifier_context(verifier_dir, git_info)
        before_manifest = file_manifest(verifier_dir)
        evidence_paths = [*git_info.changed_files, "tests/test_server.py", "TODO.md"]
        file_evidence = build_file_evidence(verifier_dir, evidence_paths)
        verifier_prompt = build_verifier_prompt(
            original_prompt,
            mandates,
            git_info,
            checks,
            (source / "TODO.md").is_file(),
            file_evidence,
        )
        _write_text(cycle_dir / "verifier" / "prompt.txt", verifier_prompt)
        progress(f"[cycle {cycle}] verifier start")
        try:
            result = run_agent(
                verifier_prompt,
                workspace=verifier_dir,
                model=args.verifier_model or args.implementer_model,
                base_url=args.base_url,
                api_key=args.api_key,
                max_steps=args.verifier_max_steps,
                timeout=args.verifier_timeout,
                reasoning=args.verifier_reasoning,
                max_tokens=args.verifier_max_tokens,
                ctx_limit=args.ctx_limit,
                progress=progress,
            )
            verifier = _agent_result_dict(result)
        except Exception as exc:
            verifier = {"status": "error", "output": str(exc), "run_id": "", "log_path": ""}

        after_manifest = file_manifest(verifier_dir)
        changed, removed, added = compare_manifests(before_manifest, after_manifest)
        verifier_read_only = not changed and not removed
        read_only_check = CheckResult(
            name="verifier_read_only",
            command="manifest comparison",
            passed=verifier_read_only,
            required=True,
            stdout="\n".join(
                [*(f"modified: {path}" for path in changed), *(f"removed: {path}" for path in removed)]
            ),
            error="" if verifier_read_only else "verifier modified existing files",
        )
        if added:
            read_only_check.stdout = (
                (read_only_check.stdout + "\n" if read_only_check.stdout else "")
                + "added files: "
                + ", ".join(added)
            )
        checks.append(read_only_check)

        tool_count = _run_tool_count(str(verifier.get("run_id") or ""))
        has_evidence = bool(file_evidence and file_evidence != "(no file evidence available)")
        inspection_check = CheckResult(
            name="verifier_inspected",
            command="coding run event and evidence inspection",
            passed=tool_count > 0 or has_evidence,
            required=True,
            stdout=f"tool calls: {tool_count}; file evidence: {'yes' if has_evidence else 'no'}",
            error="" if tool_count > 0 or has_evidence else "verifier made no tool calls and no file evidence was embedded",
        )
        checks.append(inspection_check)
        _save_checks(cycle_dir, checks)

        _write_json(cycle_dir / "verifier" / "result.json", verifier)
        _copy_run_log(verifier, cycle_dir / "verifier" / "events.jsonl")
        verifier_report = parse_verifier_report(str(verifier.get("output") or ""))
        _write_json(
            cycle_dir / "verifier" / "report.json",
            verifier_report if verifier_report is not None else {"parse_error": True, "raw_output": verifier.get("output")},
        )
        verifier_status = str(verifier.get("status") or "unknown")
        progress(
            f"[cycle {cycle}] verifier {verifier_status} "
            f"run={verifier.get('run_id')} steps={verifier.get('steps')}"
        )
        gate = gate_report(
            verifier_report,
            mandates,
            checks,
            todo_present=(source / "TODO.md").is_file(),
            verifier_status=verifier_status,
            verifier_read_only=verifier_read_only,
        )
    else:
        verifier = {
            "status": "not-run",
            "run_id": "",
            "output": "Verifier skipped.",
            "log_path": "",
        }
        _write_json(cycle_dir / "verifier" / "result.json", verifier)
        gate = gate_checks(checks)

    cycle_report = {
        "cycle": cycle,
        "implementer": implementer,
        "git": git_info.to_dict(),
        "checks": [check.to_dict() for check in checks],
        "verifier": {
            "status": verifier_status,
            "run_id": verifier.get("run_id"),
            "read_only": verifier_read_only,
            "report": verifier_report,
        },
        "gate": gate.to_dict(),
        "artifacts": str(cycle_dir),
    }
    _write_json(cycle_dir / "cycle-report.json", cycle_report)

    if not args.keep_workspaces:
        shutil.rmtree(check_workspace, ignore_errors=True)
        verifier_workspace = cycle_dir / "verifier-workspace"
        shutil.rmtree(verifier_workspace, ignore_errors=True)

    return cycle_report


def _resolve_prompt(args: argparse.Namespace) -> str:
    positional = " ".join(args.prompt).strip()
    option = (args.prompt_text or "").strip()
    if args.prompt_file and (positional or option):
        raise SystemExit("pass either --prompt-file or prompt text, not both")
    if positional and option:
        raise SystemExit("pass either a positional prompt or --prompt, not both")
    if args.prompt_file:
        return Path(args.prompt_file).expanduser().read_text(encoding="utf-8")
    if option:
        return option
    if positional:
        return positional
    raise SystemExit("a prompt, --prompt, or --prompt-file is required")


def _resolve_baseline(args: argparse.Namespace, workspace: Path) -> str | None:
    if args.baseline:
        return args.baseline
    info = collect_git_info(workspace, None)
    return info.baseline or None


def _check_dirty_workspace(workspace: Path, allow_dirty: bool) -> None:
    if allow_dirty:
        return
    info = collect_git_info(workspace, None)
    if info.error:
        return
    if info.status.strip():
        raise SystemExit(
            "workspace has uncommitted changes; commit/stash them or pass --allow-dirty "
            "(use --mode verify to audit an existing dirty workspace)"
        )


def orchestrate(args: argparse.Namespace, original_prompt: str) -> dict[str, Any]:
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise SystemExit(f"workspace is not a directory: {workspace}")

    mandates = load_mandates(Path(args.mandates_file).expanduser()) if args.mandates_file else extract_mandates(original_prompt)
    if not mandates:
        raise SystemExit("no mandates were found")

    if args.mode == "run":
        _check_dirty_workspace(workspace, args.allow_dirty)
    elif args.implementer_run_id and not args.allow_running:
        finished = _run_is_finished(args.implementer_run_id)
        if finished is False:
            raise SystemExit(
                f"implementer run {args.implementer_run_id} is still active; wait for it to finish "
                "or pass --allow-running"
            )

    artifact_root = Path(args.artifacts_dir).expanduser()
    orchestration_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    artifact_dir = artifact_root / orchestration_id
    artifact_dir.mkdir(parents=True, exist_ok=False)

    _write_text(artifact_dir / "original_prompt.txt", original_prompt.rstrip() + "\n")
    _write_json(artifact_dir / "mandates.json", [mandate.to_dict() for mandate in mandates])

    baseline = _resolve_baseline(args, workspace)
    progress = _make_progress(args.quiet)
    progress(f"[orchestrator] id={orchestration_id}")
    progress(f"[orchestrator] workspace={workspace}")
    progress(f"[orchestrator] mode={args.mode} baseline={baseline or 'unavailable'}")

    max_cycles = 1 if args.mode in {"verify", "check"} else args.max_cycles
    cycles: list[dict[str, Any]] = []
    previous_issues: list[str] = []

    for cycle in range(1, max_cycles + 1):
        cycle_report = _run_cycle(
            cycle=cycle,
            args=args,
            original_prompt=original_prompt,
            mandates=mandates,
            artifact_dir=artifact_dir,
            baseline=baseline,
            run_implementer=args.mode == "run",
            run_verifier=args.mode != "check",
            previous_issues=previous_issues,
            progress=progress,
        )
        cycles.append(cycle_report)
        if cycle_report["gate"]["passed"]:
            break
        previous_issues = _unique(
            [*cycle_report["gate"]["failures"], *_report_issues(cycle_report["verifier"]["report"])]
        )
        if args.mode != "run":
            break

    final_gate = cycles[-1]["gate"] if cycles else {"passed": False, "failures": ["no cycles ran"], "warnings": []}
    report = {
        "orchestration": {
            "id": orchestration_id,
            "mode": args.mode,
            "workspace": str(workspace),
            "baseline": baseline,
            "implementer_model": args.implementer_model,
            "verifier_model": args.verifier_model or args.implementer_model,
            "artifacts": str(artifact_dir),
        },
        "overall": "pass" if final_gate["passed"] else "fail",
        "failures": final_gate["failures"],
        "warnings": final_gate["warnings"],
        "mandates": [mandate.to_dict() for mandate in mandates],
        "cycles": cycles,
    }
    _write_json(artifact_dir / "final-report.json", report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"ORCHESTRATION {report['overall'].upper()}")
        print(f"Artifacts: {artifact_dir}")
        for failure in report["failures"]:
            print(f"FAIL: {failure}")
        for warning in report["warnings"]:
            print(f"WARN: {warning}")

    return report


def _make_progress(quiet: bool) -> Callable[[str], None]:
    def progress(message: str) -> None:
        if not quiet:
            print(message, file=sys.stderr, flush=True)

    return progress


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an implementer and an independent verifier with a hard gate.",
        allow_abbrev=False,
    )
    parser.add_argument("prompt", nargs="*", help="implementer task")
    parser.add_argument("--prompt", dest="prompt_text", default=None, help="implementer task text")
    parser.add_argument("--prompt-file", type=Path, help="read the original prompt from a file")
    parser.add_argument("--mandates-file", type=Path, help="JSON mandate checklist")
    parser.add_argument("--workspace", required=True, help="project workspace")
    parser.add_argument(
        "--mode",
        choices=("run", "verify", "check"),
        default="run",
        help="run implementer+verifier, verify existing work, or only run checks",
    )
    parser.add_argument("--baseline", default=None, help="git baseline commit")
    parser.add_argument("--implementer-run-id", default=None, help="existing implementer run id")
    parser.add_argument("--implementer-model", default=None)
    parser.add_argument("--verifier-model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--implementer-max-steps", type=int, default=DEFAULT_IMPLEMENTER_STEPS)
    parser.add_argument("--verifier-max-steps", type=int, default=DEFAULT_VERIFIER_STEPS)
    parser.add_argument("--implementer-timeout", type=float, default=DEFAULT_IMPLEMENTER_TIMEOUT)
    parser.add_argument("--verifier-timeout", type=float, default=DEFAULT_VERIFIER_TIMEOUT)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--verifier-max-tokens", type=int, default=DEFAULT_VERIFIER_MAX_TOKENS)
    parser.add_argument("--ctx-limit", type=int, default=DEFAULT_CTX_LIMIT)
    parser.add_argument("--reasoning", default="default")
    parser.add_argument("--verifier-reasoning", default="default")
    parser.add_argument("--max-cycles", type=int, default=2)
    parser.add_argument("--check-timeout", type=float, default=DEFAULT_CHECK_TIMEOUT)
    parser.add_argument("--check-command", action="append", default=[], help="custom check command")
    parser.add_argument("--protected", action="append", default=[], help="path that must not change")
    parser.add_argument("--artifacts-dir", default=str(DEFAULT_ARTIFACT_ROOT))
    parser.add_argument("--allow-dirty", action="store_true", help="allow dirty workspace in run mode")
    parser.add_argument("--allow-running", action="store_true", help="verify an active implementer run")
    parser.add_argument(
        "--keep-workspaces",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="keep check and verifier workspace copies",
    )
    parser.add_argument("--json", action="store_true", help="print the final report as JSON")
    parser.add_argument("--quiet", action="store_true", help="suppress progress output")
    parser.add_argument("--dry-run", action="store_true", help="print resolved configuration")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        original_prompt = _resolve_prompt(args)
        if args.max_cycles < 1:
            parser.error("--max-cycles must be at least 1")
        if args.dry_run:
            workspace = Path(args.workspace).expanduser().resolve()
            print(
                json.dumps(
                    {
                        "mode": args.mode,
                        "workspace": str(workspace),
                        "baseline": args.baseline,
                        "implementer_model": args.implementer_model,
                        "verifier_model": args.verifier_model or args.implementer_model,
                        "implementer_max_steps": args.implementer_max_steps,
                        "verifier_max_steps": args.verifier_max_steps,
                        "implementer_timeout": args.implementer_timeout,
                        "verifier_timeout": args.verifier_timeout,
                        "ctx_limit": args.ctx_limit,
                        "max_cycles": args.max_cycles,
                        "checks": [
                            {"name": name, "command": command}
                            for name, command in default_checks(workspace)
                        ],
                        "custom_checks": args.check_command,
                        "protected": args.protected,
                    },
                    indent=2,
                )
            )
            return 0
        report = orchestrate(args, original_prompt)
        return 0 if report["overall"] == "pass" else 1
    except SystemExit:
        raise
    except Exception as exc:
        print(f"orchestrator error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
