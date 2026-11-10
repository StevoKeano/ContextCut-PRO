"""Shared capability policy for the main agent.

Keeps the security-relevant sets in one place. The headless coding worker uses
its own stricter workspace jail (``coding_tools.Workspace``); this module
re-uses the same block/allow sets for the interactive agent while adding
path and SSRF checks that matter for a non-jailed agent.
"""

from __future__ import annotations

import ipaddress
import os
import re
import shlex
from pathlib import Path

from coding_tools import (
    ALLOWED_EXECUTABLES,
    BLOCKED_EXECUTABLES,
    GIT_DENIED_SUBCOMMANDS,
    GIT_READ_SUBCOMMANDS,
    GIT_WRITE_SUBCOMMANDS,
    PKG_ALLOWED_SUBCOMMANDS,
    PKG_DENIED_SUBCOMMANDS,
    PKG_MANAGERS,
    SECRET_DIRS,
    SECRET_NAMES,
    SECRET_PREFIXES,
    SECRET_SUFFIXES,
)

# Extra executables the interactive agent legitimately needs. They still run
# without a shell, and high-impact tools remain behind the approval gate.
AGENT_ALLOWED_EXTRA = {
    "echo",
    "cat",
    "head",
    "tail",
    "grep",
    "find",
    "sleep",
    "pwd",
    "printf",
    "touch",
    "mkdir",
    "cp",
    "sed",
    "awk",
    "sort",
    "uniq",
    "cut",
    "tr",
    "tar",
    "gzip",
    "gunzip",
    "which",
    "ps",
    "free",
    "df",
    "ss",
    "nvidia-smi",
    "uname",
    "hostname",
    "id",
    "whoami",
    "date",
    "openssl",
    "ffmpeg",
    "convert",
    "ping",
    "dig",
    "nslookup",
    "java",
    "javac",
    "rustc",
    "gcc",
    "g++",
    "go",
}

# `cp` is intentionally allowed for the agent shell (it is still blocked in
# coding_tools' own shell). High-impact shell calls still require approval.
_AGENT_BLOCKED_EXECUTABLES = BLOCKED_EXECUTABLES - {"cp"}

_FIND_EXEC_FLAGS = {
    "-exec",
    "-execdir",
    "-ok",
    "-okdir",
    "-delete",
    "-fprint",
    "-fprint0",
    "-fls",
}

_METACHARS = re.compile(r"[;|&`$<>\n\r]")

# Extra path roots that should never be read/written by the agent by default.
_SENSITIVE_ROOTS = (
    Path.home() / ".ssh",
    Path.home() / ".aws",
    Path.home() / ".gnupg",
    Path.home() / ".config",
    Path.home() / ".docker",
    Path.home() / ".kube",
    Path("/etc"),
    Path("/root"),
)

_SENSITIVE_NAMES = {
    ".bash_history",
    ".zsh_history",
    ".bashrc",
    ".zshrc",
    ".profile",
    ".bash_profile",
    ".envrc",
}

_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "instance-data",
}

_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".lan", ".home", ".localhost")


class CommandPolicyError(Exception):
    """Raised when a command is denied outright."""


class CommandNeedsApproval(Exception):
    """Raised when a command is not allowlisted and needs explicit approval."""


def _allow_sensitive() -> bool:
    return os.environ.get("CONTEXTCUT_AGENT_ALLOW_SENSITIVE", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _allow_private_fetch() -> bool:
    return os.environ.get("CONTEXTCUT_ALLOW_PRIVATE_FETCH", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def is_sensitive_path(path: str | Path) -> bool:
    """Return True if *path* points at credentials or system-sensitive files."""
    if _allow_sensitive():
        return False
    try:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        p = p.resolve()
    except Exception:
        return True

    name = p.name
    if name in SECRET_NAMES or name in _SENSITIVE_NAMES:
        return True
    if name.startswith(SECRET_PREFIXES):
        return True
    if p.suffix.lower() in SECRET_SUFFIXES:
        return True
    for part in p.parts:
        if part in SECRET_DIRS or part in _SENSITIVE_NAMES:
            return True
    for root in _SENSITIVE_ROOTS:
        try:
            root = root.expanduser().resolve()
        except Exception:
            continue
        if p == root or root in p.parents:
            return True
    return False


def parse_command(command: str, *, strict: bool = True) -> list[str]:
    """Parse and validate a shell command, returning argv.

    Does NOT execute anything. Raises ``CommandPolicyError`` for blocked
    executables or dangerous arguments, and ``CommandNeedsApproval`` for
    executables outside the allowlist.
    """
    if not command or not command.strip():
        raise CommandPolicyError("empty command")
    if "\n" in command or "\r" in command:
        raise CommandPolicyError("newlines are not allowed in commands")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise CommandPolicyError(f"could not parse command: {exc}") from exc
    if not argv:
        raise CommandPolicyError("empty command")

    for token in argv[1:]:
        if _METACHARS.search(token):
            raise CommandPolicyError(
                f"shell metacharacters are not allowed in arguments: {token!r}"
            )
        if not token.startswith("-") and (
            "/" in token or "." in token
        ) and is_sensitive_path(token):
            raise CommandPolicyError(
                f"command argument points at a sensitive path: {token!r}"
            )
    if _METACHARS.search(argv[0]):
        raise CommandPolicyError(f"invalid executable: {argv[0]!r}")

    executable = Path(argv[0]).name.lower()
    if executable in _AGENT_BLOCKED_EXECUTABLES:
        raise CommandPolicyError(f"command is blocked by policy: {executable}")
    if executable == "find":
        for arg in argv[1:]:
            if arg in _FIND_EXEC_FLAGS:
                raise CommandPolicyError(
                    f"find {arg} is blocked by policy (arbitrary execution)"
                )
    if executable == "git":
        _check_git(argv[1:])
    if executable in PKG_MANAGERS:
        _check_package_manager(executable, argv[1:])

    if (
        strict
        and executable not in ALLOWED_EXECUTABLES
        and executable not in AGENT_ALLOWED_EXTRA
    ):
        raise CommandNeedsApproval(
            f"'{executable}' is not on the allowlist; add it via "
            "CONTEXTCUT_AGENT_ALLOWLIST or approve the command explicitly."
        )
    return argv


def is_allowlisted(command: str) -> bool:
    try:
        parse_command(command)
        return True
    except CommandNeedsApproval:
        return False
    except CommandPolicyError:
        return False


def _check_git(args: list[str]) -> None:
    if not args:
        return
    sub = args[0].lower()
    if sub in GIT_DENIED_SUBCOMMANDS:
        raise CommandPolicyError(f"git subcommand is blocked by policy: git {sub}")
    if sub in GIT_READ_SUBCOMMANDS or sub in GIT_WRITE_SUBCOMMANDS:
        return
    if sub == "checkout":
        if "-b" in args:
            return
        raise CommandPolicyError("git checkout is allowed only with -b")
    if sub == "switch":
        if "-c" in args:
            return
        raise CommandPolicyError("git switch is allowed only with -c")
    raise CommandPolicyError(f"git subcommand is not on the allowlist: git {sub}")


def _check_package_manager(executable: str, args: list[str]) -> None:
    if not args:
        raise CommandPolicyError(f"{executable} requires an allowlisted subcommand")
    sub = args[0].lower()
    if sub in PKG_DENIED_SUBCOMMANDS:
        raise CommandPolicyError(f"{executable} {sub} is blocked by policy")
    if sub not in PKG_ALLOWED_SUBCOMMANDS:
        raise CommandPolicyError(
            f"{executable} {sub} is not on the allowlist (allowed: test, run)"
        )


def is_private_url(url: str) -> bool:
    """Best-effort SSRF guard for literal hosts. DNS-rebinding is not covered."""
    from urllib.parse import urlparse

    if _allow_private_fetch():
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return True
    if parsed.scheme not in ("http", "https"):
        return True
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return True
    if host in _BLOCKED_HOSTS:
        return True
    if host.endswith(_BLOCKED_HOST_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    return False


__all__ = [
    "AGENT_ALLOWED_EXTRA",
    "CommandNeedsApproval",
    "CommandPolicyError",
    "is_allowlisted",
    "is_private_url",
    "is_sensitive_path",
    "parse_command",
]
