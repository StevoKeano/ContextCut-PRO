"""Sandboxed tool layer for the headless coding worker.

File tools are jailed to a single workspace. Shell commands are allowlisted by
executable and executed without a shell, so ``;``, pipes, and redirects are not
interpreted. Secret files are denied to the file tools and secret environment
variables are scrubbed from subprocesses.

The jail is a guardrail against accidental edits outside the workspace, not a
security boundary against a malicious model: allowlisted runtimes (``python``,
``node``, ``make``, ...) execute project code with the current user's
privileges.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shlex
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from untrusted_content import wrap_untrusted

DEFAULT_MAX_READ_BYTES = 64 * 1024
DEFAULT_MAX_WRITE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024
DEFAULT_SHELL_TIMEOUT = 60
DEFAULT_LIST_LIMIT = 500

SECRET_DIRS = {".git", ".ssh", ".aws", ".gnupg", ".config"}
SECRET_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".pgpass",
    ".htpasswd",
    "credentials",
    "secrets",
}
SECRET_PREFIXES = (".env.", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore"}

BLOCKED_EXECUTABLES = {
    "sudo",
    "su",
    "doas",
    "rm",
    "rmdir",
    "mv",
    "cp",
    "chmod",
    "chown",
    "chgrp",
    "dd",
    "mkfs",
    "mount",
    "umount",
    "kill",
    "pkill",
    "killall",
    "shutdown",
    "reboot",
    "halt",
    "systemctl",
    "service",
    "apt",
    "apt-get",
    "dpkg",
    "yum",
    "dnf",
    "pacman",
    "brew",
    "curl",
    "wget",
    "ssh",
    "scp",
    "rsync",
    "nc",
    "netcat",
    "nmap",
    "docker",
    "podman",
    "kubectl",
    "bash",
    "sh",
    "zsh",
    "fish",
    "dash",
    "env",
    "xargs",
    "eval",
    "exec",
    "source",
    "npx",
    "pip",
    "pip3",
    "uv",
}

ALLOWED_EXECUTABLES = {
    "ls",
    "pwd",
    "stat",
    "file",
    "wc",
    "du",
    "diff",
    "jq",
    "sha256sum",
    "git",
    "python",
    "python3",
    "pytest",
    "ruff",
    "mypy",
    "black",
    "flake8",
    "pylint",
    "coverage",
    "node",
    "npm",
    "pnpm",
    "yarn",
    "tsc",
    "eslint",
    "prettier",
    "make",
    "cargo",
    "go",
    "cmake",
    "ninja",
    "mvn",
    "gradle",
}

GIT_READ_SUBCOMMANDS = {
    "status",
    "diff",
    "log",
    "show",
    "branch",
    "rev-parse",
    "ls-files",
    "blame",
    "tag",
}
GIT_WRITE_SUBCOMMANDS = {"add", "commit", "stash", "apply"}
GIT_DENIED_SUBCOMMANDS = {
    "push",
    "fetch",
    "pull",
    "remote",
    "config",
    "reset",
    "clean",
    "rebase",
    "merge",
    "cherry-pick",
    "revert",
    "submodule",
    "filter-branch",
    "gc",
    "prune",
    "rm",
    "mv",
    "init",
    "clone",
}

PKG_MANAGERS = {"npm", "pnpm", "yarn"}
PKG_ALLOWED_SUBCOMMANDS = {"test", "run", "--version", "-v"}
PKG_DENIED_SUBCOMMANDS = {
    "install",
    "i",
    "ci",
    "add",
    "remove",
    "uninstall",
    "publish",
    "link",
    "exec",
    "dlx",
    "create",
    "update",
}

_SECRET_ENV_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.IGNORECASE)
_EXTRA_SECRET_ENV = {
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "VOYAGE_API_KEY",
    "TYPESAFE_API_KEY",
}


class ToolError(Exception):
    """Raised for policy denials and invalid tool arguments."""


def _now() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    if size < 1024**2:
        return f"{size / 1024:.1f}KB"
    return f"{size / 1024**2:.1f}MB"


def _scrub_env(env: dict[str, str]) -> dict[str, str]:
    cleaned = {}
    for key, value in env.items():
        if key in _EXTRA_SECRET_ENV or _SECRET_ENV_RE.search(key):
            continue
        cleaned[key] = value
    return cleaned


class Workspace:
    """A jailed view of a single directory with allowlisted command execution."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_read_bytes: int = DEFAULT_MAX_READ_BYTES,
        max_write_bytes: int = DEFAULT_MAX_WRITE_BYTES,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        shell_timeout: int = DEFAULT_SHELL_TIMEOUT,
        allowed_extra: tuple[str, ...] | list[str] = (),
        passthrough_env: bool = False,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.exists():
            self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise ToolError(f"workspace is not a directory: {self.root}")
        self.max_read_bytes = max(1, int(max_read_bytes))
        self.max_write_bytes = max(1, int(max_write_bytes))
        self.max_output_bytes = max(1, int(max_output_bytes))
        self.shell_timeout = max(1, int(shell_timeout))
        self.allowed_extra = {a.strip().lower() for a in allowed_extra if a.strip()}
        self.passthrough_env = passthrough_env

    # ── path safety ──────────────────────────────────────────────────────────

    def _is_secret(self, path: Path) -> bool:
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            return True
        for part in rel.parts:
            if part in SECRET_DIRS:
                return True
        name = path.name
        if name in SECRET_NAMES:
            return True
        if name.startswith(SECRET_PREFIXES):
            return True
        if path.suffix.lower() in SECRET_SUFFIXES:
            return True
        return False

    def resolve(self, path_str: str, *, allow_secret: bool = False) -> Path:
        raw = str(path_str or "").strip()
        if not raw:
            raise ToolError("path is required")
        if "\x00" in raw:
            raise ToolError("path contains a null byte")
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        target = candidate.resolve()
        if target != self.root and not target.is_relative_to(self.root):
            raise ToolError(f"path escapes workspace: {raw}")
        if not allow_secret and self._is_secret(target):
            raise ToolError(f"path is protected (secret): {raw}")
        return target

    def _guard_write_size(self, content: str) -> None:
        size = len(content.encode("utf-8"))
        if size > self.max_write_bytes:
            raise ToolError(
                f"content is {_human_size(size)}; limit is {_human_size(self.max_write_bytes)}"
            )

    # ── file tools ───────────────────────────────────────────────────────────

    def read_file(self, path: str) -> str:
        target = self.resolve(path)
        if not target.exists():
            return f"Error: file not found: {path}"
        if not target.is_file():
            return f"Error: not a file: {path}"
        raw = target.read_bytes()
        truncated = len(raw) > self.max_read_bytes
        chunk = raw[: self.max_read_bytes]
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError:
            return f"[binary file — first 256 bytes hex]\n{chunk[:256].hex()}"
        if truncated:
            text += f"\n\n… [truncated at {self.max_read_bytes} bytes]"
        return text

    def write_file(self, path: str, content: str, backup: bool = True) -> str:
        self._guard_write_size(content)
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if backup and target.exists():
            self._backup(target)
        tmp = target.with_name(f".{target.name}.tmp-{os.getpid()}-{time.time_ns()}")
        try:
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        return f"Wrote {len(content.encode('utf-8'))} bytes to {path}"

    def append_file(self, path: str, content: str) -> str:
        self._guard_write_size(content)
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(content)
        return f"Appended {len(content.encode('utf-8'))} bytes to {path}"

    def edit_file(self, path: str, old_str: str, new_str: str, backup: bool = True) -> str:
        if not old_str:
            raise ToolError("old_str must not be empty")
        self._guard_write_size(new_str)
        target = self.resolve(path)
        if not target.exists():
            return f"Error: file not found: {path}"
        content = target.read_text(encoding="utf-8")
        count = content.count(old_str)
        if count == 0:
            return f"Error: old_str not found in {path}"
        if count > 1:
            return f"Error: old_str matches {count} locations in {path}; add more context"
        if backup:
            self._backup(target)
        updated = content.replace(old_str, new_str, 1)
        tmp = target.with_name(f".{target.name}.tmp-{os.getpid()}-{time.time_ns()}")
        try:
            tmp.write_text(updated, encoding="utf-8")
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        return f"Updated {path} (replaced {len(old_str)} chars with {len(new_str)})"

    def _backup(self, target: Path) -> None:
        backup = target.with_name(f"{target.name}.bak-{_now()}")
        shutil.copy2(target, backup)

    def list_dir(self, path: str = ".", max_depth: int = 2) -> str:
        target = self.resolve(path, allow_secret=(str(path).strip() in (".", "")))
        if not target.is_dir():
            return f"Error: not a directory: {path}"
        limit = DEFAULT_LIST_LIMIT
        lines = [str(target)]
        shown = 0

        def walk(current: Path, depth: int, prefix: str) -> None:
            nonlocal shown
            if depth > max_depth or shown >= limit:
                return
            try:
                entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
            except PermissionError:
                lines.append(f"{prefix}[permission denied]")
                return
            for entry in entries:
                if shown >= limit:
                    lines.append(f"{prefix}… [listing capped at {limit} entries]")
                    return
                if entry.name.startswith(".") or self._is_secret(entry):
                    continue
                shown += 1
                if entry.is_dir():
                    lines.append(f"{prefix}{entry.name}/")
                    walk(entry, depth + 1, prefix + "  ")
                else:
                    try:
                        size = _human_size(entry.stat().st_size)
                    except OSError:
                        size = "?"
                    lines.append(f"{prefix}{entry.name} ({size})")

        walk(target, 1, "")
        return "\n".join(lines)

    def _iter_files(self, pattern: str):
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ToolError("glob pattern must be relative and must not contain '..'")
        for entry in self.root.glob(pattern):
            resolved = entry.resolve()
            if resolved != self.root and not resolved.is_relative_to(self.root):
                continue
            if entry.is_file() and not self._is_secret(entry):
                yield entry

    def glob(self, pattern: str, limit: int = 200) -> str:
        limit = max(1, min(int(limit), 2000))
        matches = []
        for entry in self._iter_files(pattern):
            matches.append(str(entry.relative_to(self.root)))
            if len(matches) >= limit:
                matches.append(f"… [capped at {limit} matches]")
                break
        return "\n".join(matches) if matches else "(no matches)"

    def grep(self, pattern: str, path: str = ".", glob: str = "**/*", limit: int = 100) -> str:
        limit = max(1, min(int(limit), 1000))
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise ToolError(f"invalid regex: {exc}") from exc
        base = self.resolve(path, allow_secret=(str(path).strip() in (".", "")))
        if base.is_file():
            candidates = [base]
        else:
            candidates = []
            for entry in base.glob(glob):
                resolved = entry.resolve()
                if not resolved.is_relative_to(self.root):
                    continue
                if entry.is_file() and not self._is_secret(entry):
                    candidates.append(entry)
        hits = []
        for entry in sorted(candidates):
            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    hits.append(f"{entry.relative_to(self.root)}:{lineno}: {line.strip()[:300]}")
                    if len(hits) >= limit:
                        hits.append(f"… [capped at {limit} matches]")
                        return "\n".join(hits)
        return "\n".join(hits) if hits else "(no matches)"

    def copy_file(self, source: str, destination: str) -> str:
        src = self.resolve(source)
        dst = self.resolve(destination)
        if not src.is_file():
            return f"Error: source is not a file: {source}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return f"Copied {source} -> {destination}"

    def move_file(self, source: str, destination: str) -> str:
        src = self.resolve(source)
        dst = self.resolve(destination)
        if not src.exists():
            return f"Error: source not found: {source}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return f"Moved {source} -> {destination}"

    def delete_file(self, path: str) -> str:
        target = self.resolve(path)
        if not target.exists():
            return f"Error: not found: {path}"
        if target.is_dir():
            return f"Error: refusing to delete directory (use run_command sparingly): {path}"
        target.unlink()
        return f"Deleted {path}"

    # ── shell ────────────────────────────────────────────────────────────────

    def _allowed_executable(self, executable: str) -> bool:
        return executable in ALLOWED_EXECUTABLES or executable in self.allowed_extra

    def _check_command(self, argv: list[str]) -> None:
        executable = Path(argv[0]).name.lower()
        if executable in BLOCKED_EXECUTABLES:
            raise ToolError(f"command is blocked by policy: {executable}")
        if not self._allowed_executable(executable):
            raise ToolError(
                f"command is not on the allowlist: {executable}. "
                "Add it via CONTEXTCUT_CODING_ALLOWLIST if required."
            )
        if executable == "git":
            self._check_git(argv[1:])
        if executable in PKG_MANAGERS:
            self._check_package_manager(executable, argv[1:])

    def _check_git(self, args: list[str]) -> None:
        if not args:
            return
        sub = args[0].lower()
        if sub in GIT_DENIED_SUBCOMMANDS:
            raise ToolError(f"git subcommand is blocked by policy: git {sub}")
        if sub in GIT_READ_SUBCOMMANDS or sub in GIT_WRITE_SUBCOMMANDS:
            return
        if sub == "checkout":
            if "-b" in args:
                return
            raise ToolError("git checkout is allowed only with -b (new branch)")
        if sub == "switch":
            if "-c" in args:
                return
            raise ToolError("git switch is allowed only with -c (new branch)")
        raise ToolError(f"git subcommand is not on the allowlist: git {sub}")

    def _check_package_manager(self, executable: str, args: list[str]) -> None:
        if not args:
            raise ToolError(f"{executable} requires an allowlisted subcommand (test, run)")
        sub = args[0].lower()
        if sub in PKG_DENIED_SUBCOMMANDS:
            raise ToolError(f"{executable} {sub} is blocked by policy")
        if sub in PKG_ALLOWED_SUBCOMMANDS:
            return
        raise ToolError(
            f"{executable} {sub} is not on the allowlist (allowed: test, run, --version)"
        )

    def run_command(self, command: str, timeout: int | None = None) -> str:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return f"Error: could not parse command: {exc}"
        if not argv:
            return "Error: empty command"
        try:
            self._check_command(argv)
        except ToolError as exc:
            return f"Denied: {exc}"
        env = os.environ.copy() if self.passthrough_env else _scrub_env(os.environ.copy())
        limit = max(1, int(timeout)) if timeout else self.shell_timeout
        try:
            result = subprocess.run(
                argv,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=limit,
                env=env,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return f"Error: command timed out after {limit}s"
        except FileNotFoundError:
            return f"Error: executable not found: {argv[0]}"
        except Exception as exc:
            return f"Error: {exc}"

        parts = []
        out = result.stdout or ""
        err = result.stderr or ""
        if out:
            parts.append(out[: self.max_output_bytes])
            if len(out) > self.max_output_bytes:
                parts.append(f"… [stdout truncated at {self.max_output_bytes} bytes]")
        if err:
            parts.append(f"[stderr]\n{err[: self.max_output_bytes]}")
            if len(err) > self.max_output_bytes:
                parts.append(f"… [stderr truncated at {self.max_output_bytes} bytes]")
        parts.append(f"Exit code: {result.returncode}")
        return "\n".join(parts)

    def git_status(self) -> str:
        return self.run_command("git status --short --branch")

    def git_diff(self, path: str = "", staged: bool = False) -> str:
        cmd = "git diff"
        if staged:
            cmd += " --staged"
        if path:
            resolved = self.resolve(path)
            cmd += f" -- {shlex.quote(str(resolved.relative_to(self.root)))}"
        return self.run_command(cmd)


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file inside the workspace (truncated at 64 KB).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or replace a file inside the workspace (atomic, optional backup).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "backup": {"type": "boolean"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace one unique snippet (old_str) with new_str inside a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_str": {"type": "string"},
                    "new_str": {"type": "string"},
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_file",
            "description": "Append text to a file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List a directory tree inside the workspace (secrets hidden).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_depth": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Find files by glob pattern, e.g. '**/*.py'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search file contents with a regex inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "glob": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copy_file",
            "description": "Copy a file within the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "destination": {"type": "string"},
                },
                "required": ["source", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_file",
            "description": "Move or rename a file within the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "destination": {"type": "string"},
                },
                "required": ["source", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a single file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run an allowlisted command (git, python, pytest, npm test/run, make, ...) "
                "inside the workspace. No shell pipes or redirects."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "integer"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Short git status for the workspace.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show git diff, optionally for one path or staged changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "staged": {"type": "boolean"},
                },
                "required": [],
            },
        },
    },
]


def _wrap_tool_result(name: str, result: str, source: str = "") -> str:
    if result.startswith(("Error:", "Denied:")):
        return result
    return wrap_untrusted(result, source=source or f"workspace:{name}", kind=f"tool:{name}")


def dispatch(workspace: Workspace, name: str, arguments: dict) -> str:
    """Execute a tool by name, converting policy/argument errors to text."""
    if not isinstance(arguments, dict):
        return "Error: tool arguments must be a JSON object"
    for key in (
        "path",
        "content",
        "old_str",
        "new_str",
        "pattern",
        "glob",
        "source",
        "destination",
        "command",
    ):
        if key in arguments and not isinstance(arguments[key], str):
            return f"Error: invalid arguments: '{key}' must be a string"
    for key in ("limit", "max_depth"):
        if key in arguments and not isinstance(arguments[key], int):
            return f"Error: invalid arguments: '{key}' must be an integer"
    if "timeout" in arguments and not isinstance(arguments["timeout"], (int, float)):
        return "Error: invalid arguments: 'timeout' must be a number"
    try:
        if name == "read_file":
            path = arguments.get("path", "")
            return _wrap_tool_result(name, workspace.read_file(path), path)
        if name == "write_file":
            return workspace.write_file(
                arguments.get("path", ""),
                arguments.get("content", ""),
                bool(arguments.get("backup", True)),
            )
        if name == "edit_file":
            return workspace.edit_file(
                arguments.get("path", ""),
                arguments.get("old_str", ""),
                arguments.get("new_str", ""),
            )
        if name == "append_file":
            return workspace.append_file(
                arguments.get("path", ""), arguments.get("content", "")
            )
        if name == "list_dir":
            path = arguments.get("path", ".")
            return _wrap_tool_result(
                name,
                workspace.list_dir(path, int(arguments.get("max_depth", 2))),
                path,
            )
        if name == "glob":
            pattern = arguments.get("pattern", "**/*")
            return _wrap_tool_result(
                name, workspace.glob(pattern, arguments.get("limit", 200)), pattern
            )
        if name == "grep":
            pattern = arguments.get("pattern", "")
            path = arguments.get("path", ".")
            return _wrap_tool_result(
                name,
                workspace.grep(
                    pattern,
                    path,
                    arguments.get("glob", "**/*"),
                    arguments.get("limit", 100),
                ),
                f"{pattern} in {path}",
            )
        if name == "copy_file":
            return workspace.copy_file(
                arguments.get("source", ""), arguments.get("destination", "")
            )
        if name == "move_file":
            return workspace.move_file(
                arguments.get("source", ""), arguments.get("destination", "")
            )
        if name == "delete_file":
            return workspace.delete_file(arguments.get("path", ""))
        if name == "run_command":
            command = arguments.get("command", "")
            return _wrap_tool_result(
                name, workspace.run_command(command, arguments.get("timeout")), command
            )
        if name == "git_status":
            return _wrap_tool_result(name, workspace.git_status(), "git status")
        if name == "git_diff":
            path = arguments.get("path", "")
            return _wrap_tool_result(
                name,
                workspace.git_diff(path, bool(arguments.get("staged", False))),
                f"git diff {path}".strip(),
            )
    except ToolError as exc:
        return f"Denied: {exc}"
    except (TypeError, ValueError) as exc:
        return f"Error: invalid arguments: {exc}"
    except Exception as exc:
        return f"Error: {type(exc).__name__}: {exc}"
    return f"Error: unknown tool: {name}"


__all__ = [
    "Workspace",
    "ToolError",
    "TOOL_SCHEMAS",
    "dispatch",
    "ALLOWED_EXECUTABLES",
    "BLOCKED_EXECUTABLES",
    "GIT_READ_SUBCOMMANDS",
    "GIT_WRITE_SUBCOMMANDS",
]
