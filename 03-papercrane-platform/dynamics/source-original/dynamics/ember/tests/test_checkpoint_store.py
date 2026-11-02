"""Serializer-free crash/corruption tests; no model imports or execution."""

import tempfile
import unittest
from pathlib import Path

from dynamics.ember.checkpoint_store import checkpoint_reader, publish_checkpoint


class CheckpointStoreTests(unittest.TestCase):
    def test_failed_serialization_preserves_previous_and_bounds_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            alias = Path(folder) / "latest.pt"
            for payload in (b"first", b"second", b"third"):
                publish_checkpoint(alias, lambda handle: handle.write(payload))
            self.assertEqual(len(list(Path(folder).glob("*.blob"))), 2)

            def fail(handle):
                handle.write(b"partial")
                raise RuntimeError("interrupted writer")

            with self.assertRaises(RuntimeError):
                publish_checkpoint(alias, fail)
            with checkpoint_reader(alias) as (handle, digest):
                self.assertEqual(handle.read(), b"third")
                self.assertEqual(len(digest), 64)
            self.assertTrue(alias.is_symlink())

    def test_corruption_and_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            alias = Path(folder) / "latest.pt"
            publish_checkpoint(alias, lambda handle: handle.write(b"complete"))
            alias.resolve().write_bytes(b"damaged")
            with self.assertRaisesRegex(ValueError, "checksum"):
                with checkpoint_reader(alias):
                    self.fail("Corrupt checkpoint accepted")
            alias.unlink()
            alias.symlink_to("../outside.pt")
            with self.assertRaisesRegex(ValueError, "outside"):
                with checkpoint_reader(alias):
                    self.fail("External checkpoint accepted")


if __name__ == "__main__":
    unittest.main()
