from __future__ import annotations

from pathlib import Path

from flask import current_app, jsonify, request

from admin.backend.api.responses import accepted_task_response, error_response
from admin.backend.api.v1.sites import sites_bp
from admin.backend.api.v1.sites.backups import _backup_set_resource
from admin.backend.api.v1.sites.shared import (
    internal_error,
    invalid_fields,
    site_name,
    task_failure,
)
from admin.backend.middleware import require_scope
from pilot.core.bench import Bench
from pilot.internal.site_paths import site_exists
from pilot.tasks import TaskRunner


def _archived_dir(bench: Bench, name: str) -> Path:
    return bench.path / "archived" / "sites" / name


def _archived_sites(bench: Bench) -> list[tuple[str, Path]]:
    root = bench.path / "archived" / "sites"
    if not root.is_dir():
        return []
    return sorted(
        ((entry.name, entry) for entry in root.iterdir() if entry.is_dir() and not entry.is_symlink()),
        key=lambda item: item[0],
    )


def _dir_size(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total


@sites_bp.get("/archived")
def list_archived_sites():
    from admin.backend.providers.backups import BackupProvider

    bench_root = Path(current_app.config["BENCH_ROOT"])
    bench = Bench(bench_root)
    try:
        result = []
        for archived_name, directory in _archived_sites(bench):
            try:
                runs = BackupProvider(bench_root, archived_name, directory / "private" / "backups").get_local_only()
            except Exception:
                runs = []
            result.append(
                {
                    "name": archived_name,
                    "size_bytes": _dir_size(directory),
                    "created_at": directory.stat().st_mtime,
                    "backup_count": len(runs),
                    "timestamp": runs[0].timestamp if runs else None,
                }
            )
    except Exception:
        return internal_error("Could not read archived sites.")
    return jsonify(result)


@sites_bp.get("/archived/<name>/backups")
@require_scope(site_name)
def list_archived_backups(name: str):
    from admin.backend.providers.backups import BackupProvider

    bench_root = Path(current_app.config["BENCH_ROOT"])
    bench = Bench(bench_root)
    directory = _archived_dir(bench, name)
    if not directory.is_dir() or directory.is_symlink():
        return error_response("archived_site_not_found", "Archived site not found.", 404)
    try:
        runs = BackupProvider(bench_root, name, directory / "private" / "backups").get_local_only()
    except Exception:
        return internal_error("Could not read the archived site's backups.")
    return jsonify([_backup_set_resource(run) for run in runs])


@sites_bp.post("/archived/<name>/backups/<timestamp>/move")
@require_scope(site_name)
def move_archived_backup(name: str, timestamp: str):
    bench_root = Path(current_app.config["BENCH_ROOT"])
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("site"), str) or not data["site"].strip():
        return invalid_fields()
    target = data["site"].strip()
    if not site_exists(bench_root, target):
        return error_response("site_not_found", "Target site not found.", 404)
    if name == target:
        return error_response("invalid_fields", "The target site must differ from the archived site.", 422)
    try:
        task_id = TaskRunner(bench_root).run(
            "move-archived-backup",
            {"site": name, "timestamp": timestamp, "target": target},
        )
    except Exception as error:
        return task_failure(error)
    Bench(bench_root).audit_action(
        "backup",
        {"site": name, "event": "move-archived-backup", "timestamp": timestamp, "target": target},
    )
    return accepted_task_response(bench_root, task_id)


@sites_bp.delete("/archived/<name>/backups/<timestamp>")
@require_scope(site_name)
def delete_archived_backup(name: str, timestamp: str):
    bench_root = Path(current_app.config["BENCH_ROOT"])
    try:
        task_id = TaskRunner(bench_root).run(
            "delete-archived-backup",
            {"site": name, "timestamp": timestamp},
        )
    except Exception as error:
        return task_failure(error)
    Bench(bench_root).audit_action(
        "backup", {"site": name, "event": "delete-archived-backup", "timestamp": timestamp}
    )
    return accepted_task_response(bench_root, task_id)


@sites_bp.delete("/archived/<name>")
@require_scope(site_name)
def delete_archived_site(name: str):
    bench_root = Path(current_app.config["BENCH_ROOT"])
    try:
        task_id = TaskRunner(bench_root).run("delete-archived-site", {"site": name})
    except Exception as error:
        return task_failure(error)
    Bench(bench_root).audit_action("site", {"site": name, "event": "delete-archived-site"})
    return accepted_task_response(bench_root, task_id)