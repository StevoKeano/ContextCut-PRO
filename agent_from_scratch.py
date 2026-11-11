"""Robust, local tool-using coding agent for OpenAI-compatible endpoints (e.g., Strata).

Defaults:
    STRATA_BASE_URL: http://127.0.0.1:8080/v1
    STRATA_MODEL: deepseek-v4.1-flash
    STRATA_API_KEY: not-needed
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Configuration
STRATA_BASE_URL = os.environ.get("STRATA_BASE_URL", "http://127.0.0.1:8080/v1")
STRATA_MODEL = os.environ.get("STRATA_MODEL", "deepseek-v4.1-flash")
STRATA_API_KEY = os.environ.get("STRATA_API_KEY", "not-needed")
MAX_TOKENS = int(os.environ.get("STRATA_MAX_OUTPUT_TOKENS", "4096"))
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", Path.cwd())).resolve()

client = OpenAI(base_url=STRATA_BASE_URL, api_key=STRATA_API_KEY)

SYSTEM_PROMPT = f"""You are an autonomous senior software engineering assistant operating in:
{WORKSPACE_DIR}

Guidelines:
1. inspect existing codebase context before making file modifications.
2. Run shell commands to verify changes (e.g., run tests, linters, or syntax checks).
3. If an error occurs, analyze the stack trace and fix it methodically.
4. Keep file edits precise and targeted.
"""

# Terminal Colors
YOU_COLOR = "\u001b[94m"
ASSISTANT_COLOR = "\u001b[93m"
TOOL_COLOR = "\u001b[92m"
RESET_COLOR = "\u001b[0m"


# --- Path Security ---
def safe_path(path_str: str) -> Path:
    """Ensures file ops remain sandboxed inside the working directory."""
    target = (WORKSPACE_DIR / path_str).resolve()
    if not str(target).startswith(str(WORKSPACE_DIR)):
        raise PermissionError(f"Access denied: path '{path_str}' is outside workspace boundaries.")
    return target


# --- Core Tools ---
def read_file(path: str) -> str:
    p = safe_path(path)
    if not p.exists():
        return f"Error: File '{path}' does not exist."
    return p.read_text(encoding="utf-8", errors="replace")


def write_file(path: str, content: str) -> str:
    p = safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Successfully wrote {len(content)} bytes to {path}"


def edit_file(path: str, old_str: str, new_str: str) -> str:
    p = safe_path(path)
    if not p.exists():
        return f"Error: File '{path}' does not exist."
    content = p.read_text(encoding="utf-8")
    if old_str not in content:
        return f"Error: 'old_str' target block not found in {path}."
    if content.count(old_str) > 1:
        return f"Error: 'old_str' matched multiple locations in {path}. Provide more context lines."
    
    updated = content.replace(old_str, new_str, 1)
    p.write_text(updated, encoding="utf-8")
    return f"Successfully updated {path}"


def list_dir(path: str = ".") -> str:
    p = safe_path(path)
    if not p.is_dir():
        return f"Error: Path '{path}' is not a directory."
    items = []
    for entry in sorted(p.iterdir()):
        prefix = "[DIR] " if entry.is_dir() else "[FILE]"
        items.append(f"{prefix} {entry.name}")
    return "\n".join(items) if items else "Directory is empty."


def run_command(command: str, timeout_seconds: int = 60) -> str:
    try:
        res = subprocess.run(
            command,
            shell=True,
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        output = []
        if res.stdout:
            output.append(f"STDOUT:\n{res.stdout}")
        if res.stderr:
            output.append(f"STDERR:\n{res.stderr}")
        output.append(f"Exit Code: {res.returncode}")
        return "\n".join(output)
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout_seconds} seconds."
    except Exception as e:
        return f"Execution error: {str(e)}"


# --- Tool Schemas & Dispatcher ---
TOOL_MAP = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_dir": list_dir,
    "run_command": run_command,
}

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read content from a file path relative to workspace root.",
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
            "description": "Create or replace complete content of a target file.",
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
            "name": "edit_file",
            "description": "Replace precise unique code snippet (old_str) with new_str.",
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
            "name": "list_dir",
            "description": "List contents of target directory relative to workspace root.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute terminal commands (git, pytest, python, npm) inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
]


def execute_agent_loop():
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    print(f"Coding Agent initialized. Sandbox: {WORKSPACE_DIR}")
    print("Type your request or 'exit' to quit.\n")

    while True:
        try:
            user_input = input(f"{YOU_COLOR}You{RESET_COLOR}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        messages.append({"role": "user", "content": user_input})

        # Agent Reasoning Loop
        while True:
            try:
                response = client.chat.completions.create(
                    model=STRATA_MODEL,
                    messages=messages,
                    tools=TOOLS_SCHEMA,
                    max_tokens=MAX_TOKENS,
                )
            except Exception as e:
                print(f"\nAPI Call Failed: {e}")
                break

            msg = response.choices[0].message
            messages.append(msg)

            # Output Assistant Thinking / Content
            if msg.content:
                print(f"\n{ASSISTANT_COLOR}Assistant{RESET_COLOR}: {msg.content}")

            # Check if model requested tool execution
            if not msg.tool_calls:
                break

            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)

                print(f"{TOOL_COLOR}Tool Executing{RESET_COLOR}: {fn_name}({fn_args})")
                
                tool_func = TOOL_MAP.get(fn_name)
                if tool_func:
                    try:
                        result = tool_func(**fn_args)
                    except Exception as err:
                        result = f"Execution Error: {str(err)}"
                else:
                    result = f"Error: Tool '{fn_name}' not defined."

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result),
                })


if __name__ == "__main__":
    execute_agent_loop()
