"""Tests for the YAML-to-LangGraph compiler."""

from __future__ import annotations

import pytest

from selva_workflows.compiler import WorkflowCompiler
from selva_workflows.schema import (
    ContextPolicyConfig,
    ContextWindowPolicy,
    EdgeDefinition,
    NodeDefinition,
    NodeType,
    TriggerCondition,
    WorkflowDefinition,
)


def _make_workflow(**kwargs) -> WorkflowDefinition:  # type: ignore[no-untyped-def]
    defaults = {
        "name": "test",
        "nodes": [NodeDefinition(id="start", type=NodeType.PASSTHROUGH)],
    }
    defaults.update(kwargs)
    return WorkflowDefinition(**defaults)


class TestWorkflowCompiler:
    def setup_method(self) -> None:
        self.compiler = WorkflowCompiler()

    def test_compile_single_passthrough(self) -> None:
        wf = _make_workflow()
        graph = self.compiler.compile(wf)
        compiled = graph.compile()
        result = compiled.invoke({"messages": [], "status": "running"})
        assert result["current_node_id"] == "start"

    def test_compile_linear_chain(self) -> None:
        wf = _make_workflow(
            nodes=[
                NodeDefinition(id="a", type=NodeType.PASSTHROUGH),
                NodeDefinition(id="b", type=NodeType.PASSTHROUGH),
                NodeDefinition(id="c", type=NodeType.PASSTHROUGH),
            ],
            edges=[
                EdgeDefinition(source="a", target="b"),
                EdgeDefinition(source="b", target="c"),
            ],
        )
        graph = self.compiler.compile(wf)
        compiled = graph.compile()
        result = compiled.invoke({"messages": [], "status": "running"})
        assert result["current_node_id"] == "c"

    def test_compile_with_literal_node(self) -> None:
        wf = _make_workflow(
            nodes=[
                NodeDefinition(id="lit", type=NodeType.LITERAL, literal_value={"key": "val"}),
                NodeDefinition(id="end", type=NodeType.PASSTHROUGH),
            ],
            edges=[EdgeDefinition(source="lit", target="end")],
        )
        graph = self.compiler.compile(wf)
        compiled = graph.compile()
        result = compiled.invoke({"messages": [], "status": "running", "workflow_variables": {}})
        assert result["workflow_variables"]["lit"] == {"key": "val"}

    def test_compile_python_runner(self) -> None:
        wf = _make_workflow(
            nodes=[
                NodeDefinition(
                    id="calc",
                    type=NodeType.PYTHON_RUNNER,
                    code="result = 2 + 2",
                ),
            ],
        )
        graph = self.compiler.compile(wf)
        compiled = graph.compile()
        result = compiled.invoke({"messages": [], "status": "running", "workflow_variables": {}})
        assert result["workflow_variables"]["calc_result"] == 4

    def test_compile_python_runner_blocks_unsafe_code(self) -> None:
        wf = _make_workflow(
            nodes=[
                NodeDefinition(
                    id="bad",
                    type=NodeType.PYTHON_RUNNER,
                    code="result = __import__('os').system('echo hi')",
                ),
            ],
        )
        graph = self.compiler.compile(wf)
        compiled = graph.compile()
        result = compiled.invoke({"messages": [], "status": "running", "workflow_variables": {}})
        assert result["status"] == "error"
        assert result["result"] == {"error": "Python execution blocked: call to '__import__' is not allowed"}

    def test_compile_loop_counter(self) -> None:
        wf = _make_workflow(
            nodes=[
                NodeDefinition(id="counter", type=NodeType.LOOP_COUNTER, max_iterations=3),
            ],
        )
        graph = self.compiler.compile(wf)
        compiled = graph.compile()
        result = compiled.invoke({"messages": [], "status": "running", "workflow_variables": {}})
        assert result["workflow_variables"]["counter_count"] == 1
        assert result["workflow_variables"]["counter_done"] is False

    def test_compile_conditional_edges(self) -> None:
        wf = _make_workflow(
            nodes=[
                NodeDefinition(
                    id="py",
                    type=NodeType.PYTHON_RUNNER,
                    code="result = 'success'",
                ),
                NodeDefinition(id="ok", type=NodeType.PASSTHROUGH),
                NodeDefinition(id="fail", type=NodeType.PASSTHROUGH),
            ],
            edges=[
                EdgeDefinition(
                    source="py",
                    target="ok",
                    condition=TriggerCondition(keyword="success"),
                ),
                EdgeDefinition(source="py", target="fail"),
            ],
        )
        graph = self.compiler.compile(wf)
        compiled = graph.compile()
        result = compiled.invoke({"messages": [], "status": "running", "workflow_variables": {}})
        assert result["current_node_id"] == "ok"

    def test_compile_context_policy_keep_last_n(self) -> None:
        from langchain_core.messages import HumanMessage

        wf = _make_workflow(
            nodes=[
                NodeDefinition(
                    id="trimmed",
                    type=NodeType.PASSTHROUGH,
                    context_policy=ContextPolicyConfig(type=ContextWindowPolicy.KEEP_LAST_N, n=2),
                ),
            ],
        )
        graph = self.compiler.compile(wf)
        compiled = graph.compile()
        result = compiled.invoke(
            {
                "messages": [
                    HumanMessage(content="first"),
                    HumanMessage(content="second"),
                    HumanMessage(content="third"),
                ],
                "status": "running",
            }
        )
        # After trimming to last 2, the passthrough passes through
        assert len(result["messages"]) == 2

    def test_compile_rejects_invalid_workflow(self) -> None:
        wf = WorkflowDefinition(
            name="bad",
            nodes=[
                NodeDefinition(id="sub", type=NodeType.SUBGRAPH),
            ],
        )
        with pytest.raises(ValueError, match="validation failed"):
            self.compiler.compile(wf)

    def test_compile_skip_validation(self) -> None:
        """Can compile even invalid workflows when validation is disabled."""
        wf = WorkflowDefinition(
            name="bad",
            nodes=[
                NodeDefinition(id="sub", type=NodeType.SUBGRAPH),
            ],
        )
        # Should not raise
        graph = self.compiler.compile(wf, validate=False)
        assert graph is not None
