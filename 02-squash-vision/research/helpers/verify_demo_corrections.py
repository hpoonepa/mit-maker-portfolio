"""Exercise real report corrections in a disposable copy, preserving demo predictions."""
import json
import shutil
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from squashvision.app import create_app
from squashvision.settings import Settings

from prepare_demo import DATA, EVIDENCE, checked, save

manifest = json.loads((EVIDENCE / "demo.json").read_text())
destination = DATA.parent / "correction-verification-data"
if destination.exists():
    raise RuntimeError("Correction verification copy already exists; refusing to overwrite it")
destination.mkdir()
shutil.copytree(DATA / "storage", destination / "storage")
with sqlite3.connect(f"file:{DATA / 'squashvision.sqlite3'}?mode=ro", uri=True) as source:
    with sqlite3.connect(destination / "squashvision.sqlite3") as target:
        source.backup(target)

app = create_app(Settings(data_dir=destination))
match_id = manifest["matchId"]
with TestClient(app) as client:
    original = checked(client.get(f"/api/v1/matches/{match_id}/reports/latest"))
    review = checked(client.get(f"/api/v1/matches/{match_id}/review-items", params={"revision": original["revision"]}))
    assert review["items"], "Actual analysis must have a reviewable item"
    item = review["items"][0]
    command = {
        "commandType": "reject", "matchId": match_id,
        "targetType": item["reviewEntityType"], "targetId": item["reviewEntityId"],
        "expectedReportRevision": original["revision"],
        "reason": "Isolated correction API verification. This rejection is a test action and is not part of the portfolio demo report.",
        "payload": {}, "sourceTimestampUs": item["timestampUs"],
        "sourceEvidenceIds": item["evidenceIds"],
    }
    corrected = checked(client.post(f"/api/v1/matches/{match_id}/corrections", json=command))
    assert corrected["revision"] == original["revision"] + 1
    stale = client.post(f"/api/v1/matches/{match_id}/corrections", json=command)
    assert stale.status_code == 409
    preserved = checked(client.get(f"/api/v1/matches/{match_id}/reports/{original['revision']}"))
    assert preserved == original

with TestClient(create_app(Settings(data_dir=DATA))) as client:
    live_report = checked(client.get(f"/api/v1/matches/{match_id}/reports/latest"))
    assert live_report == original, "Portfolio demo must retain its untouched model report"

result = {
    "testDataDirectory": str(destination),
    "testAction": command,
    "revisionBefore": original["revision"], "revisionAfter": corrected["revision"],
    "staleRevisionStatus": stale.status_code, "staleRevisionResponse": stale.json(),
    "priorRevisionPreserved": True, "portfolioDemoReportUnchanged": True,
}
save("correction-verification.json", result)
print(json.dumps(result, indent=2))
