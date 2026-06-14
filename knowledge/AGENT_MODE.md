# Agent ON — What You Can Do

What can I expect to do with Agent ON? When you see `🤖 Agent ON` in the chat bar, the AI can now take actions on your machine instead of just returning text. Agent mode can read, write, and run files, search the web, query the knowledge base, and check system resources. This document explains what you can do with Agent ON and how to use it effectively.

## Hallucination Detection

Two layers protect against fabricated information:

**Layer 1 — Tool-usage enforcer (always on):** After the AI responds, your question is checked against keywords. If you asked for real-time data (e.g. "check my resources", "read a file", "search the web") and no tool was called, the response is blocked and the AI is re-prompted to use a tool before answering. This runs at zero extra LLM cost.

**Layer 2 — Confidence scan (opt-in):** Click the `🧪 Scan OFF` button in the chat bar to enable. After each agent response, a second lightweight LLM call scans the text and rates passages as HIGH / MEDIUM / LOW confidence. Suspect passages (MEDIUM or LOW) are highlighted with a yellow border and a ⚠/⚡ icon in the chat bubble. Hover over a highlighted passage to see why it was flagged.

## Ask me what I can do

I can read any file on your system. I can write new files and edit existing ones. I can run bash commands. I can search the web. I can query your knowledge base. I can check your CPU, RAM, disk, and GPU.

## How agent mode changes things

**Read files** — `read_file` opens configs, code, logs, any text file. Ask me "read the config" or "show me the code".

**Write and edit** — `write_file` saves new files with automatic backup. `append_file` adds to existing files. `diff_files` compares two files side by side.

**Browse directories** — `list_dir` shows what's in a folder with file sizes. Ask "what's in this directory" or "list the project files".

**Run commands** — `shell_exec` runs bash commands safely. Dangerous patterns like `rm -rf /` are blocked. Commands need your approval unless you click "Always Allow".

**Search the web** — `web_search` queries DuckDuckGo for current information. `fetch_url` grabs a page and returns the text.

**Query knowledge base** — `vector_search` searches your uploaded documents in the Qdrant RAG store. Ask "search my knowledge base" or "find documents about".

**System diagnostics** — `system_info` shows CPU percent, cores, RAM used/total, disk space, and GPU stats (if NVIDIA).

## Shell approval buttons

When I want to run a shell command, you'll see buttons: **[Allow] [Deny] [Always Allow] [Always Reject]**. Allow runs it once. Always Allow sets the session to auto-approve. Always Reject blocks all shell commands for the session.

## Example requests

"Read config.yaml and tell me the port"
"Search my knowledge base for FRCP Rule 26"
"Check disk space and find large files"
"Write a Python script to download this URL"
"Search the web for latest AI news, then summarize"
"Find the bug in this code, fix it, run the tests"
"What tools do you have available?"
"Explain what agent mode can do"
