# dbt-mcp

MCP server for dbt — inspect model errors, run models, read test results, trace lineage, and browse the project manifest.

## Install

### Via apm (recommended)
Install [apm](https://github.com/arcmesh-labs/arcmesh-pm-go) first, then:
```bash
apm install dbt-mcp
```

### Manual
```bash
git clone https://github.com/arcmesh-labs/dbt-mcp.git
pip install -r requirements.txt
```

## Configuration

Set the following environment variables before starting the server:

| Variable | Required | Default | Description |
|---|---|---|---|
| `DBT_PROJECT_DIR` | Yes | — | Absolute path to the dbt project root (the directory containing `dbt_project.yml`) |
| `DBT_PROFILES_DIR` | No | `~/.dbt` | Directory containing `profiles.yml` |
| `DBT_TARGET` | No | `dev` | dbt target name to use from `profiles.yml` (e.g. `dev`, `prod`) |

### Dev

```bash
export DBT_PROJECT_DIR=/path/to/my_project
python server.py
```

### Production target

```bash
export DBT_PROJECT_DIR=/path/to/my_project
export DBT_PROFILES_DIR=/etc/dbt
export DBT_TARGET=prod
python server.py
```

## Tools

### `get_model_error(model_name)`
Returns the outcome of the last run for a model. On failure: `status`, `message`, `compiled_sql`, and `timing`. On success: `status: "pass"`. Reads `target/run_results.json` — reflects the most recent dbt invocation.

### `run_model(model_name)`
Runs a single model programmatically against the configured warehouse target. Returns `status`, `rows_affected`, and `execution_time`. `success: true` means the call completed — check `status` to know whether dbt succeeded.

### `get_test_results(model_name=None)`
Returns test outcomes from the last dbt test run. Pass `model_name` to filter to tests for a specific model. Each result includes `test_type`, `column`, `status`, and `message`.

### `get_model_lineage(model_name)`
Returns direct `upstream` and `downstream` dependencies for a model, resolved from `target/manifest.json`. One level only — not transitive.

### `get_manifest`
Returns a compressed project overview: `project_name`, `dbt_version`, `generated_at`, counts by resource type, and a list of all models with their path and tags.

## Error handling

All tools return `{"success": false, "error": "..."}` on failure — no exceptions are raised. Tools that read from disk return `success: false` if `target/run_results.json` or `target/manifest.json` does not exist (run `dbt run` or `dbt compile` first).

## Local test environment

Requires a dbt project with a DuckDB profile. Install the adapter:

```bash
pip install dbt-duckdb>=1.7.0
```

Create a minimal `profiles.yml` if you don't have one:

```yaml
# ~/.dbt/profiles.yml
my_project:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: /tmp/dev.duckdb
```

Compile and run the project to generate the files the server reads:

```bash
export DBT_PROJECT_DIR=/path/to/my_project
dbt run --project-dir $DBT_PROJECT_DIR
dbt test --project-dir $DBT_PROJECT_DIR
python server.py
```

## Limitations (v1)

- Mostly read-only — `run_model` is the only tool that writes to the warehouse. No bulk runs, no source freshness checks.
- All read tools (`get_model_error`, `get_test_results`, `get_model_lineage`, `get_manifest`) reflect the state of the last dbt invocation, not live warehouse state.
- `run_results.json` always contains only the results of the last dbt command. dbt-mcp handles this by having `run_model` use `dbt build` (not `dbt run`), which writes both model and test results in a single operation. If you run dbt manually against the same project you should also use `dbt build` for consistent state.
- `get_model_lineage` returns one level of dependencies; multi-hop impact analysis requires chaining calls.
- Write tools (`run_test`, `run_snapshot`) and project management operations are planned for v2.
