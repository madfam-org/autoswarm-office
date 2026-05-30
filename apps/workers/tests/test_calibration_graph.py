"""Tests for load-test calibration graph."""

from __future__ import annotations

from selva_workers.graphs.calibration import build_calibration_graph, complete


class TestCalibrationGraph:
    def test_build_calibration_graph(self) -> None:
        assert build_calibration_graph() is not None

    def test_calibration_in_graph_builders(self) -> None:
        from selva_workers.__main__ import GRAPH_BUILDERS

        assert "calibration" in GRAPH_BUILDERS

    def test_complete_node(self) -> None:
        out = complete({"messages": [], "status": "running"})
        assert out["status"] == "completed"
        assert out["result"]["calibration"] is True
