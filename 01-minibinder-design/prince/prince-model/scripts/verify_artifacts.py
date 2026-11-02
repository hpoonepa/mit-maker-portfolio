"""Verify the distributed model, example, and evaluation artifact checksums."""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]


def main():
    failures = []
    entries = (ROOT / "ARTIFACTS.sha256").read_text().splitlines()
    for line in entries:
        expected, name = line.split("  ", 1)
        path = ROOT / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            failures.append(name)
    if failures:
        raise SystemExit("Artifact mismatch: " + ", ".join(failures))
    print(f"Verified {len(entries)} artifact checksums.")


if __name__ == "__main__":
    main()
