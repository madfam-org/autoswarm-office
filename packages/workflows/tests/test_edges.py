"""Tests for conditional edge evaluation."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from selva_workflows.edges import (
    END_SENTINEL,
    build_conditional_router,
    evaluate_condition,
    group_edges_by_source,
)
from selva_workflows.schema import EdgeDefinition, TriggerCondition


class TestEvaluateCondition:
    def test_regex_match(self) -> None:
        cond = TriggerCondition(regex=r"\bapproved\b")
        state = {"messages": [AIMessage(content="The request is approved.")]}
        assert evaluate_condition(cond, state) is True

    def test_regex_no_match(self) -> None:
        cond = TriggerCondition(regex=r"\brejected\b")
        state = {"messages": [AIMessage(content="The request is approved.")]}
        assert evaluate_condition(cond, state) is False

    def test_keyword_match(self) -> None:
        cond = TriggerCondition(keyword="success")
        state = {"messages": [AIMessage(content="Operation was a SUCCESS!")]}
        assert evaluate_condition(cond, state) is True

    def test_keyword_no_match(self) -> None:
        cond = TriggerCondition(keyword="failure")
        state = {"messages": [AIMessage(content="Operation was a SUCCESS!")]}
        assert evaluate_condition(cond, state) is False

    def test_expression_true(self) -> None:
        cond = TriggerCondition(expression='variables.get("score", 0) > 0.5')
        state = {"workflow_variables": {"score": 0.8}, "messages": []}
        assert evaluate_condition(cond, state) is True

    def test_expression_false(self) -> None:
        cond = TriggerCondition(expression='variables.get("score", 0) > 0.5')
        state = {"workflow_variables": {"score": 0.2}, "messages": []}
        assert evaluate_condition(cond, state) is False

    def test_expression_error_returns_false(self) -> None:
        cond = TriggerCondition(expression="undefined_var > 0")
        state = {"messages": []}
        assert evaluate_condition(cond, state) is False

    def test_expression_with_unsafe_name_returns_false(self) -> None:
        cond = TriggerCondition(expression="__import__('os').system('echo hi')")
        state = {"messages": []}
        assert evaluate_condition(cond, state) is False


class TestBuildConditionalRouter:
    def test_matches_first_condition(self) -> None:
        edges = [
            EdgeDefinition(
                source="a",
                target="yes",
                condition=TriggerCondition(keyword="approved"),
            ),
            EdgeDefinition(source="a", target="no"),
        ]
        router = build_conditional_router("a", edges)
        state = {"messages": [AIMessage(content="Request approved")]}
        assert router(state) == "yes"

    def test_falls_back_to_default(self) -> None:
        edges = [
            EdgeDefinition(
                source="a",
                target="yes",
                condition=TriggerCondition(keyword="approved"),
            ),
            EdgeDefinition(source="a", target="no"),
        ]
        router = build_conditional_router("a", edges)
        state = {"messages": [AIMessage(content="Something else")]}
        assert router(state) == "no"

    def test_no_default_returns_end(self) -> None:
        edges = [
            EdgeDefinition(
                source="a",
                target="yes",
                condition=TriggerCondition(keyword="approved"),
            ),
        ]
        router = build_conditional_router("a", edges)
        state = {"messages": [AIMessage(content="Something else")]}
        assert router(state) == END_SENTINEL


class TestGroupEdgesBySource:
    def test_groups_correctly(self) -> None:
        edges = [
            EdgeDefinition(source="a", target="b"),
            EdgeDefinition(source="a", target="c"),
            EdgeDefinition(source="b", target="c"),
        ]
        groups = group_edges_by_source(edges)
        assert len(groups["a"]) == 2
        assert len(groups["b"]) == 1
