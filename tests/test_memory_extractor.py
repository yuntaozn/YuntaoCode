"""Tests for memory_extractor: extraction prompt, tag blacklist, and dedup."""

from __future__ import annotations

import pytest

from runtime.memory_extractor import (
    EXTRACTION_SYSTEM_PROMPT,
    _BLOCKED_TAGS,
    _has_blocked_tags,
    _is_similar_to_existing,
    _normalize_text,
    _parse_extraction_result,
)


# --- Prompt contract ---

class TestExtractionPrompt:
    def test_prompt_excludes_project_knowledge(self):
        assert "项目知识" not in EXTRACTION_SYSTEM_PROMPT
        assert "项目结构" not in EXTRACTION_SYSTEM_PROMPT
        # "技术栈" may appear in exclusion rules but not as an extraction category
        assert "- 技术栈" not in EXTRACTION_SYSTEM_PROMPT

    def test_prompt_excludes_important_decision(self):
        assert "重要决策" not in EXTRACTION_SYSTEM_PROMPT
        assert "架构选择" not in EXTRACTION_SYSTEM_PROMPT

    def test_prompt_includes_user_preference(self):
        assert "用户偏好" in EXTRACTION_SYSTEM_PROMPT

    def test_prompt_includes_user_identity(self):
        assert "用户身份" in EXTRACTION_SYSTEM_PROMPT

    def test_prompt_has_explicit_exclusion_rules(self):
        assert "不要提取" in EXTRACTION_SYSTEM_PROMPT
        assert "特定项目" in EXTRACTION_SYSTEM_PROMPT


# --- Tag blacklist ---

class TestTagBlacklist:
    @pytest.mark.parametrize("tags", [
        ["project_knowledge"],
        ["tech_stack", "project_knowledge"],
        ["项目知识"],
        ["project-knowledge"],
        ["project knowledge"],
        ["architecture_decision"],
        ["technical_selection"],
        ["技术选型"],
        ["技术栈"],
        ["project-info"],
        ["project_structure"],
    ])
    def test_blocks_project_tags(self, tags):
        assert _has_blocked_tags(tags) is True

    @pytest.mark.parametrize("tags", [
        ["user_preference"],
        ["user_identity"],
        ["user-preference", "ui_preference"],
        ["communication"],
        ["tool_usage"],
        ["important_decision"],
        [],
    ])
    def test_allows_user_tags(self, tags):
        assert _has_blocked_tags(tags) is False

    def test_case_insensitive_matching(self):
        assert _has_blocked_tags(["Project_Knowledge"]) is True
        assert _has_blocked_tags(["TECH_STACK"]) is True

    def test_blocked_tags_set_is_not_empty(self):
        assert len(_BLOCKED_TAGS) > 5


# --- Normalize text ---

class TestNormalizeText:
    def test_lowercase(self):
        assert _normalize_text("Hello World") == "hello world"

    def test_strip_punctuation(self):
        result = _normalize_text("用户偏好：增量修改代码。")
        assert "：" not in result
        assert "。" not in result

    def test_collapse_whitespace(self):
        assert _normalize_text("a   b   c") == "a b c"

    def test_chinese_punctuation(self):
        result = _normalize_text("你好，世界！")
        assert "你好" in result
        assert "世界" in result
        assert "，" not in result

    def test_empty_string(self):
        assert _normalize_text("") == ""


# --- Similarity / dedup ---

class TestIsSimilarToExisting:
    def test_exact_match(self):
        existing = {_normalize_text("用户偏好增量修改代码")}
        assert _is_similar_to_existing("用户偏好增量修改代码", existing) is True

    def test_normalized_match(self):
        existing = {_normalize_text("用户偏好：增量修改代码。")}
        assert _is_similar_to_existing("用户偏好增量修改代码", existing) is True

    def test_substring_containment(self):
        existing = {_normalize_text("用户偏好基于现有文件进行增量修改")}
        assert _is_similar_to_existing("用户偏好基于现有文件进行增量修改不要重写完整文件", existing) is True

    def test_bigram_overlap(self):
        """Texts with high character bigram overlap should be detected as similar."""
        existing = {_normalize_text("用户偏好增量修改代码")}
        assert _is_similar_to_existing("用户偏好增量修改代码不重写", existing) is True

    def test_different_text_not_similar(self):
        existing = {_normalize_text("用户偏好增量修改代码")}
        assert _is_similar_to_existing("用户在Windows PowerShell环境下开发", existing) is False

    def test_empty_existing_set(self):
        assert _is_similar_to_existing("任何新记忆", set()) is False

    def test_short_text_not_substring_matched(self):
        """Short texts (< 5 chars after normalize) skip substring check."""
        existing = {_normalize_text("短文本")}
        # "短" is only 1 char, should not trigger substring match
        assert _is_similar_to_existing("完全不同的长文本内容描述", existing) is False


# --- Parse extraction result ---

class TestParseExtractionResult:
    def test_valid_json(self):
        raw = '[{"text": "用户偏好中文回复", "tags": ["user_preference"]}]'
        result = _parse_extraction_result(raw)
        assert len(result) == 1
        assert result[0]["text"] == "用户偏好中文回复"

    def test_empty_array(self):
        assert _parse_extraction_result("[]") == []

    def test_empty_string(self):
        assert _parse_extraction_result("") == []

    def test_json_with_surrounding_text(self):
        raw = '好的，以下是提取结果：\n[{"text": "test", "tags": ["t1"]}]\n完毕。'
        result = _parse_extraction_result(raw)
        assert len(result) == 1
        assert result[0]["text"] == "test"

    def test_skips_empty_text(self):
        raw = '[{"text": "", "tags": ["t1"]}, {"text": "valid", "tags": ["t2"]}]'
        result = _parse_extraction_result(raw)
        assert len(result) == 1
        assert result[0]["text"] == "valid"

    def test_invalid_json(self):
        result = _parse_extraction_result("not json at all")
        assert result == []
