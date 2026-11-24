"""DuckDB and JSON persistence for benchmark run results."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
import duckdb

from benchmark.models import RunResult


def store_result(result: RunResult, results_dir: Path) -> Path:
    path = results_dir / result.scenario_id / f"{result.run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2) + "\n")
    db_path = results_dir / "runs.duckdb"
    try:
        with duckdb.connect(str(db_path)) as connection:
            connection.execute("SET storage_compatibility_version='v1.2.0'")
            connection.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id VARCHAR PRIMARY KEY,
                scenario_id VARCHAR,
                agent_name VARCHAR,
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                status VARCHAR,
                diagnosis JSON,
                score JSON,
                budgets_used JSON,
                raw_agent_output VARCHAR,
                errors JSON
            )
            """)
            table_info = connection.execute("PRAGMA table_info('runs')").fetchall()
            columns = {row[1] for row in table_info}
            if "score" not in columns:
                connection.execute("ALTER TABLE runs ADD COLUMN score JSON")
            has_pk = any(row[1] == "run_id" and bool(row[5]) for row in table_info)
            if not has_pk:
                try:
                    connection.execute("ALTER TABLE runs ADD PRIMARY KEY (run_id)")
                except Exception:
                    try:
                        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS runs_run_id_idx ON runs (run_id)")
                    except Exception:
                        pass
            values = [
                result.run_id, result.scenario_id, result.agent_name,
                result.started_at.replace(tzinfo=None), result.finished_at.replace(tzinfo=None),
                result.status,
                result.diagnosis.model_dump_json() if result.diagnosis else None,
                result.score.model_dump_json() if result.score else None,
                json.dumps(result.budgets_used), result.raw_agent_output, json.dumps(result.errors),
            ]
            try:
                connection.execute("""
                INSERT INTO runs (
                    run_id, scenario_id, agent_name, started_at, finished_at, status,
                    diagnosis, score, budgets_used, raw_agent_output, errors
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id) DO UPDATE SET
                    scenario_id = excluded.scenario_id,
                    agent_name = excluded.agent_name,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    status = excluded.status,
                    diagnosis = excluded.diagnosis,
                    score = excluded.score,
                    budgets_used = excluded.budgets_used,
                    raw_agent_output = excluded.raw_agent_output,
                    errors = excluded.errors
                """, values)
            except duckdb.ParserException:
                exists = connection.execute("SELECT 1 FROM runs WHERE run_id = ?", [result.run_id]).fetchone()
                if exists:
                    connection.execute("""
                    UPDATE runs SET
                        scenario_id = ?, agent_name = ?, started_at = ?, finished_at = ?, status = ?,
                        diagnosis = ?, score = ?, budgets_used = ?, raw_agent_output = ?, errors = ?
                    WHERE run_id = ?
                    """, [
                        result.scenario_id, result.agent_name,
                        result.started_at.replace(tzinfo=None), result.finished_at.replace(tzinfo=None),
                        result.status,
                        result.diagnosis.model_dump_json() if result.diagnosis else None,
                        result.score.model_dump_json() if result.score else None,
                        json.dumps(result.budgets_used), result.raw_agent_output, json.dumps(result.errors),
                        result.run_id,
                    ])
                else:
                    connection.execute("""
                    INSERT INTO runs (
                        run_id, scenario_id, agent_name, started_at, finished_at, status,
                        diagnosis, score, budgets_used, raw_agent_output, errors
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, values)
    except Exception as exc:
        warnings.warn(f"Saved run JSON to {path}, but DuckDB update failed: {exc}", RuntimeWarning, stacklevel=2)
    return path
