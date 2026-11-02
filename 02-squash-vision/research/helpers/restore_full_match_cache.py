"""Restore iCloud-offloaded cache bytes from SHA-verified durable checkpoints."""
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

root = Path(__file__).resolve().parent
storage = (root / "fullmatch-data/storage").resolve()
db = sqlite3.connect(f"file:{root / 'fullmatch-data/squashvision.sqlite3'}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
rows = db.execute("select * from job_chunks where status='completed' order by chunk_index").fetchall()
records = []
for row in rows:
    def verified(relative, size, digest):
        path = (storage / relative).resolve()
        assert storage in path.parents
        data = path.read_bytes()
        assert len(data) == size and hashlib.sha256(data).hexdigest() == digest
        return data
    envelope_bytes = verified(row['artifact_path'], row['artifact_size'], row['artifact_sha256'])
    envelope = json.loads(envelope_bytes)
    payload = verified(row['artifact_payload_path'], row['artifact_payload_size'], row['artifact_payload_sha256'])
    assert envelope['payload_sha256'] == row['artifact_payload_sha256']
    assert envelope['input_hash'] == row['input_hash']
    namespace = hashlib.sha256(json.dumps({'match_id': envelope['match_id']}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    directory = storage / 'analysis-cache' / namespace / row['stage'] / row['input_hash']
    assert Path(envelope['payload_name']).name == envelope['payload_name']
    restored = []
    for name, data in [('envelope.json', envelope_bytes), (envelope['payload_name'], payload)]:
        path = directory / name
        offloaded = path.exists() and bool(path.stat().st_flags & 0x40000000)
        if not path.exists() or offloaded:
            directory.mkdir(parents=True, exist_ok=True)
            temporary = directory / f'.restore-{uuid.uuid4().hex}'
            temporary.write_bytes(data)
            temporary.replace(path)
            restored.append(name)
        else:
            assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(data).digest()
    record = {'chunk': row['chunk_index'], 'stage': row['stage'], 'rows': envelope['row_count'],
              'evidence': envelope['evidence'], 'availability': envelope['availability'], 'restored': restored}
    records.append(record)
    if restored:
        print(json.dumps(record), flush=True)
(root / 'fullmatch-verification/cache-recovery.json').write_text(json.dumps(records, indent=2))
print(f'Verified {len(records)} complete checkpoints and their cache copies', flush=True)
