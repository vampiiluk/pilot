from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass
from typing import ClassVar

from pilot.exceptions import BenchError
from pilot.tasks import Task, step

_TIMESTAMP_RE = re.compile(r"^\d{8}_\d{6}$")


@dataclass(kw_only=True)
class MoveArchivedBackupTask(Task):
    """Move one backup run from an archived site back into a live site's backups folder."""

    command: ClassVar[str] = "move-archived-backup"

    site: str
    timestamp: str
    target: str

    def run(self) -> None:
        self.require_production_privileges()
        self.move()

    @step("move", lambda self: f"Move backup {self.timestamp} of '{self.site}' to '{self.target}'")
    def move(self) -> None:
        if not _TIMESTAMP_RE.match(self.timestamp):
            raise BenchError(f"Invalid backup timestamp: {self.timestamp!r}")
        source_dir = self.bench.path / "archived" / "sites" / self.site / "private" / "backups"
        if not source_dir.is_dir():
            raise BenchError(f"No archived site '{self.site}' found.")
        destination = self.bench.site(self.target).backups.directory
        destination.mkdir(parents=True, exist_ok=True)
        moved = 0
        for path in sorted(source_dir.glob(f"{self.timestamp}-*")):
            os.replace(path, destination / path.name)
            moved += 1
        if not moved:
            raise BenchError(f"No backup files found for {self.timestamp} in archived site '{self.site}'.")


@dataclass(kw_only=True)
class DeleteArchivedBackupTask(Task):
    """Delete one backup run from an archived site's backups folder."""

    command: ClassVar[str] = "delete-archived-backup"

    site: str
    timestamp: str

    def run(self) -> None:
        self.require_production_privileges()
        self.delete()

    @step("delete", lambda self: f"Delete backup {self.timestamp} of archived site '{self.site}'")
    def delete(self) -> None:
        if not _TIMESTAMP_RE.match(self.timestamp):
            raise BenchError(f"Invalid backup timestamp: {self.timestamp!r}")
        source_dir = self.bench.path / "archived" / "sites" / self.site / "private" / "backups"
        if not source_dir.is_dir():
            raise BenchError(f"No archived site '{self.site}' found.")
        removed = 0
        for path in sorted(source_dir.glob(f"{self.timestamp}-*")):
            path.unlink()
            removed += 1
        if not removed:
            raise BenchError(f"No backup files found for {self.timestamp} in archived site '{self.site}'.")


@dataclass(kw_only=True)
class DeleteArchivedSiteTask(Task):
    """Delete an archived site entirely, including the symlink a drop leaves behind."""

    command: ClassVar[str] = "delete-archived-site"

    site: str

    def run(self) -> None:
        self.require_production_privileges()
        self.delete()

    @step("delete", lambda self: f"Delete archived site '{self.site}'")
    def delete(self) -> None:
        archived_dir = self.bench.path / "archived" / "sites" / self.site
        if not archived_dir.is_dir():
            raise BenchError(f"No archived site '{self.site}' found.")
        shutil.rmtree(archived_dir)
        link = self.bench.sites_path / self.site
        if link.is_symlink() and str(link.resolve()).startswith(str(archived_dir.resolve())):
            link.unlink()


if __name__ == "__main__":
    # The worker launches `python -m pilot.tasks.archived_sites <bench_root> <args...>`
    # with the task's positional fields, so the module dispatches on their count.
    rest = sys.argv[2:]
    if len(rest) == 3:
        MoveArchivedBackupTask.main()
    elif len(rest) == 2:
        DeleteArchivedBackupTask.main()
    else:
        DeleteArchivedSiteTask.main()