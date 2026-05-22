import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
import client

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

_RUN_RESULTS_ERROR = {
    "results": [
        {
            "unique_id": "model.my_project.orders",
            "status": "error",
            "message": "Compilation Error in model orders: undefined ref",
            "compiled_code": "SELECT * FROM undefined_ref",
            "timing": [{"name": "compile", "started_at": "2024-01-01T00:00:00", "completed_at": "2024-01-01T00:00:01"}],
        }
    ]
}

_MANIFEST = {
    "metadata": {
        "project_name": "my_project",
        "dbt_version": "1.7.0",
        "generated_at": "2024-01-01T00:00:00Z",
    },
    "nodes": {
        "model.my_project.orders": {
            "resource_type": "model",
            "name": "orders",
            "path": "marts/orders.sql",
            "tags": ["finance"],
            "depends_on": {"nodes": ["model.my_project.customers"]},
        },
        "model.my_project.customers": {
            "resource_type": "model",
            "name": "customers",
            "path": "staging/customers.sql",
            "tags": [],
            "depends_on": {"nodes": []},
        },
        "test.my_project.not_null_orders_order_id.abc123": {
            "resource_type": "test",
            "name": "not_null_orders_order_id",
            "depends_on": {"nodes": ["model.my_project.orders"]},
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "order_id"}},
            "column_name": "order_id",
        },
        "test.my_project.unique_orders_order_id.def456": {
            "resource_type": "test",
            "name": "unique_orders_order_id",
            "depends_on": {"nodes": ["model.my_project.orders"]},
            "test_metadata": {"name": "unique", "kwargs": {"column_name": "order_id"}},
            "column_name": "order_id",
        },
    },
    "sources": {
        "source.my_project.raw.events": {},
    },
    "child_map": {
        "model.my_project.orders": ["model.my_project.revenue"],
        "model.my_project.customers": ["model.my_project.orders"],
    },
}

_RUN_RESULTS_TESTS = {
    "results": [
        {
            "unique_id": "test.my_project.not_null_orders_order_id.abc123",
            "status": "pass",
            "message": "",
        },
        {
            "unique_id": "test.my_project.unique_orders_order_id.def456",
            "status": "fail",
            "message": "Got 3 results, configured to fail if != 0",
        },
    ]
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dbt_runner_mock(status: str, rows_affected: int = 42, execution_time: float = 1.5):
    """Build a sys.modules patch for dbt.cli.main with a single node result."""
    node = SimpleNamespace(name="orders")
    node_result = SimpleNamespace(
        status=status,
        adapter_response={"rows_affected": rows_affected},
        execution_time=execution_time,
        message="adapter error detail" if status == "error" else None,
        node=node,
    )
    run_result = SimpleNamespace(results=[node_result])
    invocation = SimpleNamespace(exception=None, result=run_result)

    runner_instance = MagicMock()
    runner_instance.invoke.return_value = invocation

    mock_module = MagicMock()
    mock_module.dbtRunner = MagicMock(return_value=runner_instance)
    return mock_module


# ---------------------------------------------------------------------------
# get_model_error
# ---------------------------------------------------------------------------

def test_get_model_error_returns_error_details():
    with patch("client._load_run_results", return_value=_RUN_RESULTS_ERROR):
        result = client.get_model_error("orders")

    assert result["success"] is True
    assert result["model"] == "orders"
    assert result["status"] == "error"
    assert "Compilation Error" in result["message"]
    assert result["compiled_sql"] == "SELECT * FROM undefined_ref"
    assert isinstance(result["timing"], list)
    assert len(result["timing"]) == 1


def test_get_model_error_missing_file():
    with patch("client._load_run_results", return_value={}):
        result = client.get_model_error("orders")

    assert result["success"] is False
    assert isinstance(result["error"], str)
    assert len(result["error"]) > 0


# ---------------------------------------------------------------------------
# run_model
# ---------------------------------------------------------------------------

def test_run_model_success(monkeypatch):
    monkeypatch.setenv("DBT_PROJECT_DIR", "/fake/project")
    mock_dbt = _dbt_runner_mock(status="success", rows_affected=42, execution_time=1.5)

    with patch.dict(sys.modules, {"dbt": MagicMock(), "dbt.cli": MagicMock(), "dbt.cli.main": mock_dbt}):
        result = client.run_model("orders")

    assert result["success"] is True
    assert result["model"] == "orders"
    assert result["status"] == "success"
    assert result["rows_affected"] == 42
    assert result["execution_time"] == 1.5
    assert "message" not in result


def test_run_model_dbt_exception(monkeypatch):
    monkeypatch.setenv("DBT_PROJECT_DIR", "/fake/project")

    invocation = SimpleNamespace(
        exception=RuntimeError("Model 'nonexistent' not found in project"),
        result=None,
    )
    runner_instance = MagicMock()
    runner_instance.invoke.return_value = invocation

    mock_module = MagicMock()
    mock_module.dbtRunner = MagicMock(return_value=runner_instance)

    with patch.dict(sys.modules, {"dbt": MagicMock(), "dbt.cli": MagicMock(), "dbt.cli.main": mock_module}):
        result = client.run_model("nonexistent")

    assert result["success"] is False
    assert isinstance(result["error"], str)
    assert len(result["error"]) > 0


# ---------------------------------------------------------------------------
# get_test_results
# ---------------------------------------------------------------------------

def test_get_test_results_mixed_pass_fail():
    with (
        patch("client._load_run_results", return_value=_RUN_RESULTS_TESTS),
        patch("client._load_manifest", return_value=_MANIFEST),
    ):
        result = client.get_test_results("orders")

    assert result["success"] is True
    assert result["total"] == 2
    assert result["passed"] == 1
    assert result["failed"] == 1

    by_name = {t["name"]: t for t in result["tests"]}
    assert by_name["not_null_orders_order_id"]["status"] == "pass"
    assert by_name["not_null_orders_order_id"]["test_type"] == "not_null"
    assert by_name["not_null_orders_order_id"]["column"] == "order_id"
    assert by_name["unique_orders_order_id"]["status"] == "fail"
    assert "Got 3 results" in by_name["unique_orders_order_id"]["message"]


def test_get_test_results_missing_file():
    with patch("client._load_run_results", return_value={}):
        result = client.get_test_results()

    assert result["success"] is False
    assert isinstance(result["error"], str)
    assert len(result["error"]) > 0


# ---------------------------------------------------------------------------
# get_model_lineage
# ---------------------------------------------------------------------------

def test_get_model_lineage_upstream_and_downstream():
    with patch("client._load_manifest", return_value=_MANIFEST):
        result = client.get_model_lineage("orders")

    assert result["success"] is True
    assert result["model"] == "orders"
    assert result["node_id"] == "model.my_project.orders"
    assert "customers" in result["upstream"]
    assert "revenue" in result["downstream"]


def test_get_model_lineage_model_not_in_manifest():
    with patch("client._load_manifest", return_value=_MANIFEST):
        result = client.get_model_lineage("nonexistent_model")

    assert result["success"] is False
    assert isinstance(result["error"], str)
    assert "nonexistent_model" in result["error"]


# ---------------------------------------------------------------------------
# get_manifest
# ---------------------------------------------------------------------------

def test_get_manifest_returns_compressed_summary():
    with patch("client._load_manifest", return_value=_MANIFEST):
        result = client.get_manifest()

    assert result["success"] is True
    assert result["project_name"] == "my_project"
    assert result["dbt_version"] == "1.7.0"
    assert result["generated_at"] == "2024-01-01T00:00:00Z"
    assert result["model_count"] == 2
    assert result["source_count"] == 1
    assert result["test_count"] == 2

    model_names = [m["name"] for m in result["models"]]
    assert "orders" in model_names
    assert "customers" in model_names

    orders_entry = next(m for m in result["models"] if m["name"] == "orders")
    assert orders_entry["path"] == "marts/orders.sql"
    assert orders_entry["tags"] == ["finance"]
    assert orders_entry["node_id"] == "model.my_project.orders"


def test_get_manifest_missing_file():
    with patch("client._load_manifest", return_value={}):
        result = client.get_manifest()

    assert result["success"] is False
    assert isinstance(result["error"], str)
    assert len(result["error"]) > 0
