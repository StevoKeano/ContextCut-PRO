"""Tests for the shared agent shell/path/SSRF policy."""

import pytest

from agent_policy import (
    CommandNeedsApproval,
    CommandPolicyError,
    is_allowlisted,
    is_private_url,
    is_sensitive_path,
    parse_command,
)


class TestParseCommand:
    @pytest.mark.parametrize(
        "cmd",
        [
            "echo hi",
            "ls -la",
            "git status",
            "git diff --stat",
            "cp /tmp/a /tmp/b",
            "make test",
            "sleep 1",
        ],
    )
    def test_allowed_commands(self, cmd):
        assert parse_command(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo hi; rm -rf /",
            "echo hi && curl http://attacker.invalid",
            "echo $(whoami)",
            "cat file | sh",
            "rm -rf /",
            "sudo id",
        ],
    )
    def test_rejects_metacharacters_and_blocked_executables(self, cmd):
        with pytest.raises(CommandPolicyError):
            parse_command(cmd)

    def test_unknown_command_needs_approval(self):
        with pytest.raises(CommandNeedsApproval):
            parse_command("definitely-not-a-real-binary --flag")

    def test_find_exec_is_blocked(self):
        with pytest.raises(CommandPolicyError):
            parse_command("find . -name '*.py' -exec rm {} ;")

    def test_sensitive_path_argument_blocked(self):
        with pytest.raises(CommandPolicyError):
            parse_command("cat ~/.ssh/id_rsa")
        with pytest.raises(CommandPolicyError):
            parse_command("grep token .env")

    def test_is_allowlisted(self):
        assert is_allowlisted("echo hi")
        assert not is_allowlisted("echo hi; id")
        assert not is_allowlisted("definitely-not-a-real-binary")


class TestSensitivePaths:
    def test_common_secret_files(self):
        assert is_sensitive_path("~/.ssh/id_rsa")
        assert is_sensitive_path(".env")
        assert is_sensitive_path("/etc/passwd")

    def test_normal_project_file(self):
        assert not is_sensitive_path("/home/steve/dev/ContextCut-PRO/README.md")


class TestPrivateUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:11434",
            "http://127.0.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://192.168.1.1/",
            "file:///etc/passwd",
            "http://metadata.google.internal/",
        ],
    )
    def test_blocked(self, url):
        assert is_private_url(url)

    @pytest.mark.parametrize("url", ["https://example.com", "http://8.8.8.8/"])
    def test_public(self, url):
        assert not is_private_url(url)
