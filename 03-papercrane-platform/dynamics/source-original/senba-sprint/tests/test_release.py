import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from senba_sprint import release


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def manifest(files, repository=release.REPOSITORY):
    return json.dumps({
        "repository": repository,
        "revision": release.REVISION,
        "files": [
            {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            for path, data in files.items()
        ],
    }).encode()


def opener(files, raw_manifest=None):
    raw_manifest = manifest(files) if raw_manifest is None else raw_manifest

    def urlopen(url, timeout):
        assert timeout == 30
        if "release-manifest.json" in url:
            return Response(raw_manifest)
        for path, data in files.items():
            if path in url:
                return Response(data)
        raise OSError("unexpected URL")

    return urlopen


class ReleaseTests(unittest.TestCase):
    def test_downloads_metadata_and_preserves_manifest(self):
        files = {"README.md": b"hello", "config.json": b"{}"}
        raw = manifest(files)
        with tempfile.TemporaryDirectory() as directory, patch.object(
            release, "urlopen", opener(files, raw)
        ):
            report = release.fetch_release(directory)
            self.assertTrue(report["ok"])
            self.assertEqual((Path(directory) / "release-manifest.json").read_bytes(), raw)
            self.assertEqual((Path(directory) / "README.md").read_bytes(), b"hello")
            self.assertTrue((Path(directory) / release.SNAPSHOT_NAME).is_file())

    def test_checkpoint_is_excluded_by_default(self):
        files = {"README.md": b"hello", "model.ckpt": b"tiny-test-weight"}
        with tempfile.TemporaryDirectory() as directory, patch.object(
            release, "urlopen", opener(files)
        ):
            report = release.fetch_release(directory)
            checkpoint = next(item for item in report["files"] if item["path"].endswith(".ckpt"))
            self.assertFalse(checkpoint["selected"])
            self.assertFalse((Path(directory) / "model.ckpt").exists())

    def test_manifest_mismatch_does_not_stop_later_downloads(self):
        files = {"README.md": b"changed", "config.json": b"later"}
        parsed = json.loads(manifest(files))
        parsed["files"][0]["sha256"] = "0" * 64
        raw = json.dumps(parsed).encode()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            release, "urlopen", opener(files, raw)
        ):
            report = release.fetch_release(directory)
            self.assertFalse(report["ok"])
            self.assertFalse(report["files"][0]["matched"])
            self.assertTrue((Path(directory) / "config.json").is_file())

    def test_existing_conflict_is_never_overwritten(self):
        files = {"README.md": b"remote"}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "README.md"
            target.write_bytes(b"local")
            with patch.object(release, "urlopen", opener(files)):
                report = release.fetch_release(directory)
            self.assertEqual(target.read_bytes(), b"local")
            self.assertEqual(report["files"][0]["disposition"], "existing_cache_conflict")
            self.assertFalse(report["files"][0]["available"])

    def test_identical_cached_file_is_reused(self):
        files = {"README.md": b"same"}
        raw = manifest(files)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath("README.md").write_bytes(b"same")
            root.joinpath("release-manifest.json").write_bytes(raw)
            with patch.object(release, "urlopen", opener(files, raw)):
                report = release.fetch_release(directory)
            self.assertEqual(report["files"][0]["disposition"], "reused_identical")

    def test_repeat_fetch_reuses_stable_snapshot(self):
        files = {"README.md": b"same"}
        with tempfile.TemporaryDirectory() as directory, patch.object(
            release, "urlopen", opener(files)
        ):
            release.fetch_release(directory)
            report = release.fetch_release(directory)
        self.assertEqual(report["snapshot_disposition"], "reused_identical")
        self.assertTrue(report["ok"])

    def test_manifest_repository_warning_does_not_redirect(self):
        files = {"README.md": b"pip install pikachuandme1/senba"}
        raw = manifest(files, repository="pikachuandme1/senba")
        seen = []
        fake = opener(files, raw)

        def tracking(url, timeout):
            seen.append(url)
            return fake(url, timeout)

        with tempfile.TemporaryDirectory() as directory, patch.object(release, "urlopen", tracking):
            report = release.fetch_release(directory)
        self.assertTrue(all(release.REPOSITORY in url for url in seen))
        self.assertTrue(any("no redirect" in warning for warning in report["warnings"]))
        self.assertTrue(any("stale repository" in warning for warning in report["warnings"]))

    def test_actual_manifest_hash_prefix_and_size_bytes_are_normalized(self):
        data = b"public release readme"
        digest = hashlib.sha256(data).hexdigest()
        raw = json.dumps({
            "repository": "pikachuandme1/senba",
            "revision": release.REVISION,
            "files": [{
                "path": "README.md",
                "sha256": f"sha256:{digest}",
                "size_bytes": len(data),
            }],
        }).encode()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            release, "urlopen", opener({"README.md": data}, raw)
        ):
            report = release.fetch_release(directory)
            snapshot = json.loads((Path(directory) / release.SNAPSHOT_NAME).read_text())
        self.assertTrue(report["files"][0]["matched"])
        self.assertEqual(report["files"][0]["expected"]["sha256"], digest)
        self.assertTrue(any("pikachuandme1/senba" in warning for warning in snapshot["warnings"]))

    def test_rejects_unsafe_paths_and_excessive_sizes(self):
        bad_paths = ("../secret", "/absolute", "https://evil.test/a", "dir\\file")
        for path in bad_paths:
            raw = json.dumps({"files": [{"path": path, "sha256": "0" * 64, "size": 1}]}).encode()
            with self.subTest(path=path), tempfile.TemporaryDirectory() as directory, patch.object(
                release, "urlopen", opener({}, raw)
            ):
                with self.assertRaises(ValueError):
                    release.fetch_release(directory)
        raw = json.dumps({"files": [{
            "path": "README.md", "sha256": "0" * 64, "size": release.MAX_TEXT_BYTES + 1
        }]}).encode()
        with tempfile.TemporaryDirectory() as directory, patch.object(release, "urlopen", opener({}, raw)):
            with self.assertRaisesRegex(ValueError, "size cap"):
                release.fetch_release(directory)

    def test_checkpoint_uses_pinned_expectation(self):
        data = b"tiny-test-weight"
        files = {"model.ckpt": data}
        with tempfile.TemporaryDirectory() as directory, patch.object(
            release, "urlopen", opener(files)
        ):
            report = release.fetch_release(directory, include_checkpoint=True)
        item = report["files"][0]
        self.assertEqual(item["pinned_expected"]["sha256"], release.CHECKPOINT_SHA256)
        self.assertFalse(item["matched"])
        self.assertEqual(item["disposition"], "downloaded")


if __name__ == "__main__":
    unittest.main()
