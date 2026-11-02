from __future__ import annotations

import os
import re
import shutil
import stat
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select

from squashvision.models import AssetKind, MediaAsset

if TYPE_CHECKING:
    from squashvision.db import Database


_KIND_DIRECTORIES: dict[AssetKind, tuple[str, ...]] = {
    AssetKind.ORIGINAL: ("videos", "original"),
    AssetKind.PROXY: ("videos", "proxy"),
    AssetKind.FRAME: ("frames",),
    AssetKind.TIMESTAMP_MAP: ("timestamp-maps",),
    AssetKind.EXPORT: ("exports",),
    AssetKind.MODEL: ("models",),
}
_SIMPLE_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,10}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MODEL_TEMPORARY = re.compile(r"\.asset-[0-9a-f]{32}\.tmp\Z")
_ROOT_ORPHAN = re.compile(
    r"(?:"
    r"\.upload-[0-9a-f]{32}\.tmp|"
    r"\.proxy-[0-9a-f]{32}\.mp4|"
    r"\.timestamp-[0-9a-f]{32}\.json|"
    r"\.timestamp-index-[0-9a-f]{32}"
    r")\Z"
)
_PUBLISHED_ORPHANS: tuple[
    tuple[Path, re.Pattern[str], re.Pattern[str]], ...
] = (
    (
        Path("videos", "original"),
        re.compile(r"[0-9a-f]{32}\.[a-z0-9]{1,10}\Z"),
        re.compile(
            r"\.[0-9a-f]{32}\.[a-z0-9]{1,10}\.[0-9a-f]{32}\.tmp\Z"
        ),
    ),
    (
        Path("videos", "proxy"),
        re.compile(r"[0-9a-f]{32}\.mp4\Z"),
        re.compile(r"\.[0-9a-f]{32}\.mp4\.[0-9a-f]{32}\.tmp\Z"),
    ),
    (
        Path("timestamp-maps"),
        re.compile(r"[0-9a-f]{32}\.json\Z"),
        re.compile(r"\.[0-9a-f]{32}\.json\.[0-9a-f]{32}\.tmp\Z"),
    ),
    (
        Path("timestamp-index"),
        re.compile(r"[0-9a-f]{32}\.parquet\Z"),
        re.compile(
            r"\.[0-9a-f]{32}\.parquet\.[0-9a-f]{32}\.tmp\Z"
        ),
    ),
    (
        Path("exports"),
        re.compile(r"[0-9a-f]{32}\.zip\Z"),
        re.compile(r"\.[0-9a-f]{32}\.zip\.[0-9a-f]{32}\.tmp\Z"),
    ),
)


@dataclass(frozen=True, slots=True)
class StoredPath:
    relative: Path
    absolute: Path


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)
        self.root.mkdir(parents=True, exist_ok=True)
        root_stat = self.root.stat()
        self._root_identity = (root_stat.st_dev, root_stat.st_ino)

    def allocate(self, kind: AssetKind, suffix: str) -> StoredPath:
        if not _SIMPLE_SUFFIX.fullmatch(suffix):
            raise ValueError("suffix must be one dot followed by 1-10 ASCII letters or digits")
        try:
            directory_parts = _KIND_DIRECTORIES[kind]
        except KeyError as error:
            raise ValueError(f"unsupported asset kind: {kind}") from error

        relative = Path(*directory_parts, f"{uuid4().hex}{suffix.lower()}")
        self._ensure_parent_directories(relative)
        return StoredPath(relative=relative, absolute=self._absolute_for(relative))

    def allocate_timestamp_index(self) -> StoredPath:
        relative = Path("timestamp-index", f"{uuid4().hex}.parquet")
        self._ensure_parent_directories(relative)
        return StoredPath(
            relative=relative,
            absolute=self._absolute_for(relative),
        )

    @contextmanager
    def create_timestamp_index_stage(
        self,
    ) -> Iterator[tuple[StoredPath, int]]:
        directory_relative = Path(f".timestamp-index-{uuid4().hex}")
        file_relative = directory_relative / "index.parquet"
        root_fd = self._open_root_fd()
        directory_fd: int | None = None
        file_fd: int | None = None
        created = False
        try:
            os.mkdir(directory_relative.name, mode=0o700, dir_fd=root_fd)
            created = True
            directory_flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            directory_fd = os.open(
                directory_relative.name,
                directory_flags,
                dir_fd=root_fd,
            )
            directory_info = os.fstat(directory_fd)
            if (
                not stat.S_ISDIR(directory_info.st_mode)
                or directory_info.st_uid != os.geteuid()
                or stat.S_IMODE(directory_info.st_mode) != 0o700
            ):
                raise ValueError(
                    "timestamp index staging directory is not private"
                )
            file_fd = os.open(
                file_relative.name,
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            file_info = os.fstat(file_fd)
            if (
                not stat.S_ISREG(file_info.st_mode)
                or file_info.st_uid != os.geteuid()
                or file_info.st_nlink != 1
                or stat.S_IMODE(file_info.st_mode) != 0o600
            ):
                raise ValueError("timestamp index staging file is not private")
            yield (
                StoredPath(
                    relative=file_relative,
                    absolute=self.root / file_relative,
                ),
                file_fd,
            )
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if created:
                expected_identity = (
                    (directory_info.st_dev, directory_info.st_ino)
                    if directory_fd is not None
                    else None
                )
                for name in os.listdir(root_fd):
                    try:
                        entry = os.stat(
                            name,
                            dir_fd=root_fd,
                            follow_symlinks=False,
                        )
                    except FileNotFoundError:
                        continue
                    if expected_identity == (entry.st_dev, entry.st_ino):
                        self._remove_entry_at(root_fd, name)
                        break
                self._remove_entry_at(root_fd, directory_relative.name)
                os.fsync(root_fd)
            if directory_fd is not None:
                os.close(directory_fd)
            os.close(root_fd)

    def create_model_temporary(self) -> Path:
        relative = Path("models", f".asset-{uuid4().hex}.tmp")
        self._ensure_parent_directories(relative)
        parent_fd, name = self._open_parent_fd(relative)
        try:
            temporary_fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=parent_fd,
            )
            os.close(temporary_fd)
        finally:
            os.close(parent_fd)
        return self._absolute_for(relative)

    def cleanup_model_temporaries(self) -> None:
        relative = Path("models", ".cleanup")
        self._ensure_parent_directories(relative)
        parent_fd, _ = self._open_parent_fd(relative)
        removed = False
        try:
            for name in os.listdir(parent_fd):
                if _MODEL_TEMPORARY.fullmatch(name):
                    self._unlink_at(parent_fd, name)
                    removed = True
            if removed:
                os.fsync(parent_fd)
        finally:
            os.close(parent_fd)


    def reconcile_orphans(
        self,
        *,
        owned_paths: Iterable[Path],
        protected_trees: Iterable[Path],
    ) -> None:
        owned = {
            self._validate_relative(path) for path in owned_paths
        }
        protected = {
            self._validate_relative(path) for path in protected_trees
        }
        root_fd = self._open_root_fd()
        try:
            changed = False
            for name in os.listdir(root_fd):
                if _ROOT_ORPHAN.fullmatch(name) is None:
                    continue
                self._remove_entry_at(root_fd, name)
                changed = True
            if changed:
                os.fsync(root_fd)
        finally:
            os.close(root_fd)

        for directory, published_name, temporary_name in _PUBLISHED_ORPHANS:
            try:
                parent_fd, _ = self._open_parent_fd(
                    directory / ".cleanup"
                )
            except ValueError:
                continue
            try:
                changed = False
                for name in os.listdir(parent_fd):
                    relative = directory / name
                    if (
                        temporary_name.fullmatch(name) is not None
                        or (
                            published_name.fullmatch(name) is not None
                            and relative not in owned
                        )
                    ):
                        self._remove_entry_at(parent_fd, name)
                        changed = True
                if changed:
                    os.fsync(parent_fd)
            finally:
                os.close(parent_fd)

        try:
            checkpoints_fd, _ = self._open_parent_fd(
                Path("checkpoints", ".cleanup")
            )
        except ValueError:
            return
        try:
            self._prune_unowned_checkpoints(
                checkpoints_fd,
                Path("checkpoints"),
                owned,
                protected,
            )
        finally:
            os.close(checkpoints_fd)

    def publish_model(self, prepared: Path, sha256: str, suffix: str) -> StoredPath:
        if not _SHA256.fullmatch(sha256):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        if not _SIMPLE_SUFFIX.fullmatch(suffix):
            raise ValueError("suffix must be one dot followed by 1-10 ASCII letters or digits")
        relative = Path("models", f"{sha256}{suffix.lower()}")
        stored = StoredPath(relative=relative, absolute=self._absolute_for(relative))
        self._ensure_parent_directories(relative)

        prepared = Path(os.path.abspath(prepared))
        models_directory = self._absolute_for(Path("models"))
        if (
            prepared.parent != models_directory
            or not prepared.name.startswith(".asset-")
            or not prepared.name.endswith(".tmp")
        ):
            raise ValueError("prepared model is not a managed temporary sibling")
        prepared_stat = prepared.lstat()
        if not stat.S_ISREG(prepared_stat.st_mode):
            raise ValueError("prepared model must be a regular file")

        parent_fd, destination_name = self._open_parent_fd(relative)
        try:
            self._reject_final_symlink(parent_fd, destination_name)
            os.replace(
                prepared.name,
                destination_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        return stored

    def delete_model(self, relative: Path) -> None:
        validated = self._validate_relative(relative)
        if len(validated.parts) != 2 or validated.parts[0] != "models":
            raise ValueError("model path must be a direct child of the models directory")
        parent_fd, name = self._open_parent_fd(validated)
        try:
            self._reject_final_symlink(parent_fd, name)
            self._unlink_at(parent_fd, name)
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

    def resolve(
        self, relative: Path, *, owned_paths: Iterable[Path]
    ) -> StoredPath:
        validated = self._validate_relative(relative)
        owned = {self._validate_relative(path) for path in owned_paths}
        if validated not in owned:
            raise PermissionError("path is not owned by a database record")
        absolute = self._absolute_for(validated)
        parent_fd, name = self._open_parent_fd(validated)
        try:
            self._reject_final_symlink(parent_fd, name)
        finally:
            os.close(parent_fd)
        return StoredPath(relative=validated, absolute=absolute)

    def open_owned(
        self,
        relative: Path,
        *,
        owned_paths: Iterable[Path],
    ) -> int:
        validated = self._validate_relative(relative)
        owned = {self._validate_relative(path) for path in owned_paths}
        if validated not in owned:
            raise PermissionError("path is not owned by a database record")
        parent_fd, name = self._open_parent_fd(validated)
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
        finally:
            os.close(parent_fd)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            os.close(descriptor)
            raise ValueError("owned path must be a regular file")
        return descriptor

    def publish_descriptor(
        self, stored: StoredPath, source_descriptor: int
    ) -> StoredPath:
        self._validate_allocation(stored)
        source_info = os.fstat(source_descriptor)
        if not stat.S_ISREG(source_info.st_mode):
            raise ValueError("published source must be a regular file")
        parent_fd, destination_name = self._open_parent_fd(stored.relative)
        temporary_name = f".{destination_name}.{uuid4().hex}.tmp"
        temporary_created = False
        source_position = os.lseek(source_descriptor, 0, os.SEEK_CUR)
        try:
            self._reject_final_symlink(parent_fd, destination_name)
            temporary_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=parent_fd,
            )
            temporary_created = True
            os.lseek(source_descriptor, 0, os.SEEK_SET)
            with os.fdopen(temporary_fd, "wb") as output:
                while block := os.read(source_descriptor, 1024 * 1024):
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            os.replace(
                temporary_name,
                destination_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            temporary_created = False
            os.fsync(parent_fd)
        finally:
            os.lseek(source_descriptor, source_position, os.SEEK_SET)
            if temporary_created:
                self._unlink_at(parent_fd, temporary_name)
            os.close(parent_fd)
        return stored

    def remove_owned_tree(
        self,
        relative: Path,
        *,
        owned_paths: Iterable[Path],
    ) -> None:
        validated = self._validate_relative(relative)
        owned = {self._validate_relative(path) for path in owned_paths}
        if validated not in owned:
            raise PermissionError("path is not owned by a database record")
        parent_fd, name = self._open_parent_fd(validated)
        try:
            self._remove_entry_at(parent_fd, name)
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

    @classmethod
    def _prune_unowned_checkpoints(
        cls,
        directory_fd: int,
        prefix: Path,
        owned: set[Path],
        protected: set[Path],
    ) -> None:
        changed = False
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        for name in os.listdir(directory_fd):
            relative = prefix / name
            inside_protected = any(
                relative.parts[: len(path.parts)] == path.parts
                for path in protected
                if len(path.parts) <= len(relative.parts)
            )
            if relative in owned or inside_protected:
                continue
            has_descendant = any(
                path.parts[: len(relative.parts)] == relative.parts
                for path in (*owned, *protected)
                if len(path.parts) > len(relative.parts)
            )
            if not has_descendant:
                cls._remove_entry_at(directory_fd, name)
                changed = True
                continue
            try:
                info = os.stat(
                    name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(info.st_mode):
                continue
            try:
                child_fd = os.open(name, flags, dir_fd=directory_fd)
            except OSError:
                continue
            try:
                cls._prune_unowned_checkpoints(
                    child_fd,
                    relative,
                    owned,
                    protected,
                )
            finally:
                os.close(child_fd)
        if changed:
            os.fsync(directory_fd)

    @classmethod
    def _remove_entry_at(cls, parent_fd: int, name: str) -> None:
        try:
            entry = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(entry.st_mode):
            os.unlink(name, dir_fd=parent_fd)
            return
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        directory_fd = os.open(name, flags, dir_fd=parent_fd)
        try:
            for child in os.listdir(directory_fd):
                cls._remove_entry_at(directory_fd, child)
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        os.rmdir(name, dir_fd=parent_fd)

    def publish(self, stored: StoredPath, source: Path) -> StoredPath:
        self._validate_allocation(stored)
        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError(source)

        is_original = stored.relative.parts[:2] == ("videos", "original")
        parent_fd, destination_name = self._open_parent_fd(stored.relative)
        temporary_name = f".{destination_name}.{uuid4().hex}.tmp"
        temporary_created = False
        try:
            self._reject_final_symlink(parent_fd, destination_name)
            temporary_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=parent_fd,
            )
            temporary_created = True
            with source.open("rb") as source_file, os.fdopen(
                temporary_fd, "wb"
            ) as temporary_file:
                shutil.copyfileobj(source_file, temporary_file)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                if is_original:
                    os.fchmod(temporary_file.fileno(), 0o444)
            if is_original:
                try:
                    os.link(
                        temporary_name,
                        destination_name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError as error:
                    raise FileExistsError(
                        "published original assets are immutable"
                    ) from error
            else:
                os.replace(
                    temporary_name,
                    destination_name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                temporary_created = False
        finally:
            if temporary_created:
                self._unlink_at(parent_fd, temporary_name)
            os.close(parent_fd)

        return stored

    def delete_media_asset(self, database: Database, asset_public_id: str) -> None:
        parent_fd: int | None = None
        destination_name: str | None = None
        staged_name: str | None = None
        staged_active = False
        try:
            with database.session() as session:
                asset = session.scalar(
                    select(MediaAsset).where(MediaAsset.public_id == asset_public_id)
                )
                if asset is None:
                    raise LookupError(f"media asset not found: {asset_public_id}")
                relative = self._validate_relative(Path(asset.relative_path))
                self._absolute_for(relative)
                parent_fd, destination_name = self._open_parent_fd(relative)
                self._reject_final_symlink(parent_fd, destination_name)
                staged_name = (
                    f".{destination_name}.{uuid4().hex}.deleting"
                )
                os.replace(
                    destination_name,
                    staged_name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                staged_active = True
                staged_stat = os.stat(
                    staged_name, dir_fd=parent_fd, follow_symlinks=False
                )
                if not stat.S_ISREG(staged_stat.st_mode):
                    os.rename(
                        staged_name,
                        destination_name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                    )
                    staged_active = False
                    raise ValueError(
                        "database-owned asset path is a symlink or non-file"
                    )
                session.delete(asset)
        except BaseException:
            if (
                staged_active
                and parent_fd is not None
                and destination_name is not None
                and staged_name is not None
            ):
                os.link(
                    staged_name,
                    destination_name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                self._unlink_at(parent_fd, staged_name)
            raise
        else:
            if staged_active and parent_fd is not None and staged_name is not None:
                self._unlink_at(parent_fd, staged_name)
        finally:
            if parent_fd is not None:
                os.close(parent_fd)

    def _validate_allocation(self, stored: StoredPath) -> Path:
        relative = self._validate_relative(stored.relative)
        destination = self._absolute_for(relative)
        supplied_absolute = Path(os.path.abspath(stored.absolute))
        if supplied_absolute != destination:
            raise ValueError("stored absolute path does not match the storage root")
        return destination

    def _absolute_for(self, relative: Path) -> Path:
        validated = self._validate_relative(relative)
        candidate = self.root
        for part in validated.parts:
            candidate /= part
            if candidate.is_symlink():
                raise ValueError("path contains a symlink component")
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise ValueError("path escapes the storage root") from error
        return candidate

    def _open_root_fd(self) -> int:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
            os, "O_NOFOLLOW", 0
        )
        root_fd = os.open(self.root, flags)
        root_stat = os.fstat(root_fd)
        if (root_stat.st_dev, root_stat.st_ino) != self._root_identity:
            os.close(root_fd)
            raise ValueError("storage root changed after initialization")
        return root_fd

    def _open_parent_fd(self, relative: Path) -> tuple[int, str]:
        validated = self._validate_relative(relative)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
            os, "O_NOFOLLOW", 0
        )
        current_fd = self._open_root_fd()
        try:
            for part in validated.parts[:-1]:
                try:
                    next_fd = os.open(part, flags, dir_fd=current_fd)
                except OSError as error:
                    raise ValueError(
                        "path contains a symlink or unsafe directory component"
                    ) from error
                os.close(current_fd)
                current_fd = next_fd
            return current_fd, validated.name
        except BaseException:
            os.close(current_fd)
            raise

    def _ensure_parent_directories(self, relative: Path) -> None:
        validated = self._validate_relative(relative)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
            os, "O_NOFOLLOW", 0
        )
        current_fd = self._open_root_fd()
        try:
            for part in validated.parts[:-1]:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                try:
                    next_fd = os.open(part, flags, dir_fd=current_fd)
                except OSError as error:
                    raise ValueError(
                        "path contains a symlink or unsafe directory component"
                    ) from error
                os.close(current_fd)
                current_fd = next_fd
        finally:
            os.close(current_fd)

    @staticmethod
    def _reject_final_symlink(parent_fd: int, name: str) -> None:
        try:
            entry_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(entry_stat.st_mode):
            raise ValueError("path contains a symlink component")

    @staticmethod
    def _unlink_at(parent_fd: int, name: str) -> None:
        try:
            os.unlink(name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass

    @staticmethod
    def _validate_relative(relative: Path) -> Path:
        candidate = Path(relative)
        if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
            raise ValueError("path must be a non-empty relative path without '..'")
        return candidate
