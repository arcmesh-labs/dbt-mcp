import json
import os
from pathlib import Path
from typing import Any


def _project_dir() -> Path:
    return Path(os.environ["DBT_PROJECT_DIR"])


def _profiles_dir() -> str:
    return os.environ.get("DBT_PROFILES_DIR", str(Path.home() / ".dbt"))


def _target() -> str:
    return os.environ.get("DBT_TARGET", "dev")


def _load_run_results() -> dict[str, Any]:
    path = _project_dir() / "target" / "run_results.json"
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def _load_manifest() -> dict[str, Any]:
    path = _project_dir() / "target" / "manifest.json"
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def _model_results_from(results: list[dict], model_name: str) -> list[dict]:
    """Filter run_results entries belonging to a specific model node."""
    matched = []
    for r in results:
        uid = r.get("unique_id", "")
        parts = uid.split(".")
        if parts[0] == "model" and parts[-1] == model_name:
            matched.append(r)
    return matched


# ---------------------------------------------------------------------------
# get_model_error
# ---------------------------------------------------------------------------


def get_model_error(model_name: str) -> dict[str, Any]:
    try:
        run_results = _load_run_results()
        if not run_results:
            return {"success": False, "error": "run_results.json not found"}

        results = run_results.get("results", [])
        model_results = _model_results_from(results, model_name)

        if not model_results:
            return {
                "success": False,
                "error": f"Model '{model_name}' not found in run_results.json",
            }

        last = model_results[-1]
        status = last.get("status", "unknown")

        if status == "success":
            return {"success": True, "model": model_name, "status": "pass"}

        return {
            "success": True,
            "model": model_name,
            "status": status,
            "message": last.get("message", ""),
            "compiled_sql": last.get("compiled_code") or last.get("compiled_sql", ""),
            "timing": last.get("timing", []),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# run_model
# ---------------------------------------------------------------------------


def run_model(model_name: str) -> dict[str, Any]:
    try:
        from dbt.cli.main import dbtRunner  # type: ignore[import]

        invocation = dbtRunner().invoke([
            "build",
            "--select", model_name,
            "--project-dir", str(_project_dir()),
            "--profiles-dir", _profiles_dir(),
            "--target", _target(),
        ])

        if invocation.exception:
            return {"success": False, "error": str(invocation.exception)}

        run_result = invocation.result
        if run_result is None or not getattr(run_result, "results", None):
            return {
                "success": True,
                "model": model_name,
                "status": "no_results",
                "rows_affected": None,
                "execution_time": None,
            }

        node_result = next(
            (r for r in run_result.results if getattr(r.node, "name", None) == model_name),
            run_result.results[0],
        )

        status = str(node_result.status)
        adapter_response = getattr(node_result, "adapter_response", {}) or {}
        rows_affected = adapter_response.get("rows_affected")
        execution_time = getattr(node_result, "execution_time", None)
        message = getattr(node_result, "message", None)

        out: dict[str, Any] = {
            "success": True,
            "model": model_name,
            "status": status,
            "rows_affected": rows_affected,
            "execution_time": execution_time,
        }
        if status == "error" and message:
            out["message"] = message
        return out
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# get_test_results
# ---------------------------------------------------------------------------


def get_test_results(model_name: str | None = None) -> dict[str, Any]:
    try:
        run_results = _load_run_results()
        if not run_results:
            return {"success": False, "error": "run_results.json not found"}

        results = run_results.get("results", [])
        test_results = [r for r in results if r.get("unique_id", "").startswith("test.")]

        manifest = _load_manifest()
        manifest_nodes = manifest.get("nodes", {}) if manifest else {}

        # When filtering by model, find test node IDs that depend on the model
        filter_ids: set[str] | None = None
        if model_name and manifest_nodes:
            model_node_ids = {
                nid for nid, n in manifest_nodes.items()
                if n.get("resource_type") == "model" and n.get("name") == model_name
            }
            filter_ids = {
                nid for nid, n in manifest_nodes.items()
                if n.get("resource_type") == "test"
                and any(mid in n.get("depends_on", {}).get("nodes", []) for mid in model_node_ids)
            }

        tests: list[dict[str, Any]] = []
        for r in test_results:
            uid = r.get("unique_id", "")
            if filter_ids is not None and uid not in filter_ids:
                continue

            node_info = manifest_nodes.get(uid, {})
            test_meta = node_info.get("test_metadata", {})
            kwargs = test_meta.get("kwargs", {})

            # Resolve which model this test belongs to
            resolved_model = model_name
            if not resolved_model and node_info:
                for dep_id in node_info.get("depends_on", {}).get("nodes", []):
                    dep = manifest_nodes.get(dep_id, {})
                    if dep.get("resource_type") == "model":
                        resolved_model = dep.get("name")
                        break

            tests.append({
                "name": node_info.get("name") or uid.split(".")[2] if uid.count(".") >= 2 else uid,
                "model": resolved_model,
                "status": r.get("status", "unknown"),
                "message": r.get("message", ""),
                "test_type": test_meta.get("name"),
                "column": kwargs.get("column_name") or node_info.get("column_name"),
            })

        passed = sum(1 for t in tests if t["status"] in ("pass", "success"))
        failed = sum(1 for t in tests if t["status"] in ("fail", "error"))

        return {
            "success": True,
            "total": len(tests),
            "passed": passed,
            "failed": failed,
            "tests": tests,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# get_model_lineage
# ---------------------------------------------------------------------------


def get_model_lineage(model_name: str) -> dict[str, Any]:
    try:
        manifest = _load_manifest()
        if not manifest:
            return {"success": False, "error": "manifest.json not found"}

        nodes = manifest.get("nodes", {})

        model_node_id = next(
            (nid for nid, n in nodes.items()
             if n.get("resource_type") == "model" and n.get("name") == model_name),
            None,
        )
        if model_node_id is None:
            return {"success": False, "error": f"Model '{model_name}' not found in manifest"}

        node = nodes[model_node_id]

        upstream = [
            uid.split(".")[-1]
            for uid in node.get("depends_on", {}).get("nodes", [])
        ]

        # child_map includes tests and exposures — keep only model nodes
        child_map = manifest.get("child_map", {})
        if model_node_id in child_map:
            downstream = [
                cid.split(".")[-1]
                for cid in child_map[model_node_id]
                if cid.startswith("model.")
            ]
        else:
            downstream = [
                n.get("name", nid.split(".")[-1])
                for nid, n in nodes.items()
                if n.get("resource_type") == "model"
                and model_node_id in n.get("depends_on", {}).get("nodes", [])
                and nid != model_node_id
            ]

        return {
            "success": True,
            "model": model_name,
            "node_id": model_node_id,
            "upstream": upstream,
            "downstream": downstream,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# get_manifest
# ---------------------------------------------------------------------------


def get_manifest() -> dict[str, Any]:
    try:
        manifest = _load_manifest()
        if not manifest:
            return {"success": False, "error": "manifest.json not found"}

        metadata = manifest.get("metadata", {})
        nodes = manifest.get("nodes", {})
        sources = manifest.get("sources", {})

        models = []
        test_count = 0
        for nid, node in nodes.items():
            rt = node.get("resource_type")
            if rt == "model":
                models.append({
                    "name": node.get("name"),
                    "node_id": nid,
                    "path": node.get("path") or node.get("original_file_path", ""),
                    "tags": node.get("tags", []),
                })
            elif rt == "test":
                test_count += 1

        return {
            "success": True,
            "project_name": metadata.get("project_name", ""),
            "dbt_version": metadata.get("dbt_version", ""),
            "generated_at": metadata.get("generated_at", ""),
            "model_count": len(models),
            "source_count": len(sources),
            "test_count": test_count,
            "models": models,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
