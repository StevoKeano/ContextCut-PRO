"""
Tests for ContextCut PRO self-knowledge: capabilities doc, always-on blurb, and
the meta-question router used to inject the full doc on demand.
"""

import pytest

from capabilities import (
    CAPABILITIES_BLURB,
    capabilities_block,
    capabilities_text,
    is_meta_question,
)


class TestIsMetaQuestion:
    @pytest.mark.parametrize(
        "text",
        [
            "what can you do for me",
            "what can you do",
            "how can you help me",
            "what are you",
            "who are you",
            "tell me about yourself",
            "what are your capabilities",
            "what are your features",
            "what can contextcut do",
            "what is contextcut",
            "how does contextcut work",
            "how do you work",
            "how do I use you",
            "how do I use contextcut",
            "how to use you",
            "how do I use you to code",
            "how do I code with you",
            "how do I work with you",
            "how do I get started",
            "how do I set you up",
            "what tools do you have",
            "what features does contextcut have",
            "help me get started",
        ],
    )
    def test_matches(self, text):
        assert is_meta_question(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "how do I use Python",
            "how do I use the requests library",
            "write a function to parse dates",
            "what is the capital of France",
            "explain quantum physics",
            "read the file config.yaml",
            "how do I use this file",
        ],
    )
    def test_does_not_match(self, text):
        assert is_meta_question(text) is False


class TestCapabilitiesText:
    def test_returns_doc(self):
        text = capabilities_text()
        assert "ContextCut PRO" in text
        assert len(text) > 200

    def test_is_cached(self):
        assert capabilities_text() is capabilities_text()

    def test_block_is_marked_trusted(self):
        block = capabilities_block()
        assert block.startswith("## ContextCut PRO capabilities")
        assert "trusted" in block
        assert "ContextCut PRO" in block

    def test_blurb_is_compact(self):
        assert "ContextCut PRO" in CAPABILITIES_BLURB
        assert "contextcut_help" in CAPABILITIES_BLURB
        assert len(CAPABILITIES_BLURB) < 2000


class TestContextCutHelpTool:
    def test_registered_in_all_tools(self):
        import agent_handler as ah

        names = [t.name for t in ah.ALL_TOOLS]
        assert "contextcut_help" in names

    def test_present_in_tool_descriptions(self):
        import agent_handler as ah

        assert "contextcut_help" in ah.TOOL_DESCRIPTIONS

    def test_returns_capabilities_doc(self):
        import agent_handler as ah

        result = ah.contextcut_help.invoke({})
        assert "ContextCut PRO" in result
        assert result.strip() == capabilities_text().strip()


class TestSystemPromptBlurb:
    def test_agent_system_prompt_includes_blurb(self):
        import agent_handler as ah

        assert CAPABILITIES_BLURB in ah.get_system_prompt()

    def test_agent_system_prompt_has_self_knowledge_rule(self):
        import agent_handler as ah

        assert "contextcut_help()" in ah.get_system_prompt()

    def test_system_base_includes_blurb(self):
        import qdrant_proxy_final as qp

        assert CAPABILITIES_BLURB in qp.SYSTEM_BASE


class TestInjectContextMeta:
    def _content(self, result):
        return result["messages"][0]["content"]

    def test_meta_query_injects_capabilities(self):
        from qdrant_proxy_final import inject_context

        body = {"messages": [{"role": "user", "content": "what can you do"}]}
        result = inject_context(body, "", "what can you do")
        content = self._content(result)
        assert "## ContextCut PRO capabilities" in content
        assert "ContextCut PRO is a local" in content

    def test_non_meta_query_omits_capabilities(self):
        from qdrant_proxy_final import inject_context

        body = {"messages": [{"role": "user", "content": "how do I use Python"}]}
        result = inject_context(body, "", "how do I use Python")
        content = self._content(result)
        assert "## ContextCut PRO capabilities" not in content

    def test_meta_block_is_trusted_and_ctx_stays_untrusted_last(self):
        from qdrant_proxy_final import inject_context
        from untrusted_content import END_MARKER

        body = {"messages": [{"role": "user", "content": "what can you do"}]}
        result = inject_context(body, "some context", "what can you do")
        content = self._content(result)
        assert "## ContextCut PRO capabilities" in content
        assert "semantic search, untrusted" in content
        assert content.rstrip("\n").endswith(END_MARKER + "\n\n---")

    def test_meta_with_existing_system_message(self):
        from qdrant_proxy_final import inject_context

        body = {
            "messages": [
                {"role": "system", "content": "You are a helpful bot."},
                {"role": "user", "content": "how do I get started"},
            ]
        }
        result = inject_context(body, "", "how do I get started")
        content = self._content(result)
        assert content.startswith("You are a helpful bot.")
        assert "## ContextCut PRO capabilities" in content

    def test_two_arg_call_still_works(self):
        from qdrant_proxy_final import inject_context

        body = {"messages": [{"role": "user", "content": "hello"}]}
        result = inject_context(body, "context")
        content = self._content(result)
        assert "helpful AI assistant" in content
        assert "## ContextCut PRO capabilities" not in content
