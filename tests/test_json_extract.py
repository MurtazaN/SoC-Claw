"""Tests for ``blue_lantern.llm.json_extract.extract_json``.

This is the robustness layer every agent leans on to pull a JSON object out of
free-text LLM output. The tests pin the three extraction paths (direct parse,
fenced, regex fallback) and document the known greedy-match limitation
(first ``{`` to last ``}``) so a future fix flips an assertion deliberately.
"""

import pytest

from blue_lantern.llm.json_extract import extract_json


class TestDirectParse:
    def test_bare_object(self):
        assert extract_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}

    def test_bare_array(self):
        assert extract_json("[1, 2, 3]") == [1, 2, 3]

    def test_surrounding_whitespace(self):
        assert extract_json('   \n {"a": 1}\n  ') == {"a": 1}


class TestMarkdownFences:
    def test_json_fenced(self):
        text = '```json\n{"severity": "P1"}\n```'
        assert extract_json(text) == {"severity": "P1"}

    def test_bare_fence_no_language(self):
        text = '```\n{"severity": "P2"}\n```'
        assert extract_json(text) == {"severity": "P2"}


class TestRegexFallback:
    def test_object_embedded_in_prose(self):
        # Direct parse fails; the greedy {…} grabs the single object.
        text = 'Here is the verdict: {"severity": "P3"} — done.'
        assert extract_json(text) == {"severity": "P3"}

    def test_nested_braces_in_single_object(self):
        # Greedy matching is what lets nested braces survive.
        text = 'noise {"a": 1, "b": {"c": 2}} trailing'
        assert extract_json(text) == {"a": 1, "b": {"c": 2}}

    def test_array_embedded_in_prose(self):
        text = "results: [1, 2, 3] end"
        assert extract_json(text) == [1, 2, 3]


class TestFailureModes:
    @pytest.mark.parametrize("text", ["", "no json here at all", "{not valid}"])
    def test_unparseable_raises_valueerror(self, text):
        with pytest.raises(ValueError, match="Could not extract valid JSON"):
            extract_json(text)

    def test_two_objects_with_junk_between_recovers_first(self):
        # raw_decode stops after the first complete object, so junk + a second
        # object after it no longer breaks extraction (finding #5 fix).
        text = 'prefix {"a": 1} junk {"b": 2} suffix'
        assert extract_json(text) == {"a": 1}

    def test_trailing_prose_after_object(self):
        text = '{"severity": "P1"} \n\nThat is my analysis.'
        assert extract_json(text) == {"severity": "P1"}
