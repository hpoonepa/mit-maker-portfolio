"""Retrieve public dataset documentation/tables, never submit private inputs."""
from paths import DATA, REPO, MODEL
import hashlib,json,urllib.request
from pathlib import Path
HERE=Path(__file__).resolve().parent
DEST=DATA / 'minibinder-data';DEST.mkdir(parents=True, exist_ok=True)
BASE='https://huggingface.co/datasets/Anthropic/claude-protein-binder-design/resolve/main/'
API='https://huggingface.co/api/datasets/Anthropic/claude-protein-binder-design/tree/main/data/tables'
req=urllib.request.Request(API,headers={'User-Agent':'PRINCE-site-research/0.1'})
with urllib.request.urlopen(req,timeout=60) as response:listing=json.load(response)
(DEST/'table_listing.json').write_text(json.dumps(listing,indent=2)+'\n')
files=['README.md','data/README.md','data/docs/DATA_NOTES.md','data/docs/INSILICO.md','data/docs/WETLAB.md','data/tables/design_summary.parquet','data/tables/column_dictionary.parquet']
for row in listing:
    if row['type']=='file' and any(x in row['path'] for x in ['epitope','target_construct']):files.append(row['path'])
receipts=[]
for path in dict.fromkeys(files):
    dest=DEST/path;dest.parent.mkdir(parents=True,exist_ok=True)
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE+path,headers={'User-Agent':'PRINCE-site-research/0.1'}),timeout=90) as response:data=response.read()
        dest.write_bytes(data);receipts.append({'path':path,'url':BASE+path,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()});print(path,len(data),flush=True)
    except Exception as exc:receipts.append({'path':path,'error':repr(exc)});print(path,repr(exc),flush=True)
(DEST/'acquisition.json').write_text(json.dumps({'source':'Anthropic/claude-protein-binder-design','license':'CC BY 4.0 data/documentation, third-party exceptions per upstream','files':receipts},indent=2)+'\n')
