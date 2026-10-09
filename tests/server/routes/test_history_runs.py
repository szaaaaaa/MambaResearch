"""Saved files provide research history, not execution status."""

from pathlib import Path
from datetime import datetime, timedelta, timezone

from src.server.routes import history_runs

from src.server.routes.history_runs import scan_outputs_dir


def test_saved_artifacts_do_not_imply_task_execution_or_completion(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    assert scan_outputs_dir(outputs) == []
    snapshots = {}
    for run_id, filename, content in (
        ("lit_review_20261009_120000", "report.md", "# Unreviewed draft"),
        ("exp_20261009_130000", "plan.md", "# Not started\n- [ ] Run experiment"),
    ):
        run = outputs / run_id
        run.mkdir(parents=True)
        artifact = run / filename
        artifact.write_text(content, encoding="utf-8")
        snapshots[artifact] = artifact.read_bytes()

    records = scan_outputs_dir(outputs)
    assert [row["run_id"] for row in records] == [
        "exp_20261009_130000", "lit_review_20261009_120000",
    ]
    assert [row["artifacts"] for row in records] == [["plan.md"], ["report.md"]]
    assert [row["title"] for row in records] == ["Not started", "Unreviewed draft"]
    assert all(not {"status", "finished_at", "source_asset"}.intersection(row) for row in records)
    assert {path: path.read_bytes() for path in snapshots} == snapshots


def test_run_directory_local_time_is_not_reinterpreted_as_utc(tmp_path: Path, monkeypatch) -> None:
    class LocalDateTime(datetime):
        def timestamp(self):
            return datetime.timestamp(self.replace(tzinfo=self.tzinfo or timezone(timedelta(hours=8))))

    monkeypatch.setattr(history_runs, "datetime", LocalDateTime)
    (tmp_path / "exp_20261009_001500").mkdir()
    records = scan_outputs_dir(tmp_path)
    assert records[0]["started_at"] == int(datetime(2026, 10, 8, 16, 15, tzinfo=timezone.utc).timestamp())
