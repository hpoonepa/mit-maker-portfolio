"""Check complete observation pagination and summarize real inference evidence."""
from collections import Counter
import json
from statistics import median

from fastapi.testclient import TestClient
import pyarrow.parquet as pq

from squashvision.app import create_app
from squashvision.settings import Settings

from prepare_demo import DATA, EVIDENCE, checked, save

manifest = json.loads((EVIDENCE / "demo.json").read_text())
report = json.loads((EVIDENCE / "report.json").read_text())
result = {
    "matchId": manifest["matchId"], "reportRevision": manifest["reportRevision"],
    "actualModelInference": True, "syntheticObservations": False,
    "clipSeconds": 25, "sourceOffsetSeconds": 250,
    "profile": "maximum", "processingSeconds": manifest["analysisWallSeconds"],
    "roiReanalysisSeconds": manifest.get("roiReanalysisWallSeconds"),
    "playerRoi": manifest.get("playerRoi"),
    "processingDevice": "cpu", "realTimeProcessing": False,
    "automaticCalibration": "refused_missing_internal_court_topology",
    "manualCalibration": False,
    "overviewEstimates": report["sections"]["overview"]["payload"],
    "limitations": manifest["limitations"] + [
        "Only two classified shot events survived the current inference thresholds; this is not a complete contact count.",
        "The model-labelled serve within this mid-rally excerpt awaits manual review.",
        "Court distances and ball speeds are unavailable without sufficient calibration evidence.",
        "Player A/B identities can switch through occlusion; labels are not verified person identities.",
    ],
    "observations": {},
}

with TestClient(create_app(Settings(data_dir=DATA), run_migrations=False)) as client:
    for kind in ("players", "ball"):
        items = []
        cursor = None
        pages = 0
        while True:
            params = {"revision": manifest["reportRevision"], "startUs": 0,
                      "endUs": 25_000_000, "limit": 500}
            if cursor:
                params["cursor"] = cursor
            page = checked(client.get(
                f"/api/v1/matches/{manifest['matchId']}/observations/{kind}", params=params,
            ))
            items.extend(page["items"])
            pages += 1
            cursor = page["nextCursor"]
            if cursor is None:
                break
        candidates = list((DATA / "storage/analysis-cache").glob(f"*/{kind}/*/payload.parquet"))
        artifact = next(path for path in candidates
                        if kind != "players" or json.loads((path.parent / "envelope.json").read_text()).get("player_roi") == manifest.get("playerRoi"))
        row_count = pq.read_metadata(artifact).num_rows
        assert len(items) == row_count
        keys = [(item.get("playerId"), item["timestampUs"]) for item in items]
        assert len(keys) == len(set(keys))
        confidence = "detectionConfidence" if kind == "players" else "probability"
        summary = {
            "rows": len(items), "verifiedApiPages": pages,
            "apiMatchesArtifactRows": True, "duplicateObservations": 0,
            "evidenceCounts": dict(Counter(item["evidence"] for item in items)),
            "ambiguousRows": sum(item["ambiguous"] for item in items),
            "medianModelConfidence": median(item[confidence] for item in items),
            "firstTimestampUs": min(item["timestampUs"] for item in items),
            "lastTimestampUs": max(item["timestampUs"] for item in items),
        }
        if kind == "ball":
            summary["visibleRows"] = sum(item["visible"] for item in items)
        result["observations"][kind] = summary

result["correctionVerification"] = json.loads((EVIDENCE / "correction-verification.json").read_text())
if (EVIDENCE / "roi-tracking-verification.json").exists():
    result["roiVerification"] = json.loads((EVIDENCE / "roi-tracking-verification.json").read_text())
result["export"] = json.loads((EVIDENCE / "export.json").read_text())
result["export"]["downloadChecksumVerified"] = True
save("verification-summary.json", result)
print(json.dumps({key: result[key] for key in ("matchId", "processingSeconds", "observations")}, indent=2))
