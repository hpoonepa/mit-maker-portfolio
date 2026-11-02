import { useState } from 'react';
const resources=[
  ['Model evaluation','model-evaluation.json','JSON','The fitted structural model, split accounting, residue metrics, and provenance.'],
  ['Site evaluation','site-evaluation.json','JSON','Completed patch-selection outcomes for all 110 test interfaces.'],
  ['Uncertainty & paired comparisons','site-uncertainty.json','JSON','Top-k definitions, component-bootstrap intervals, and paired differences.'],
  ['Fit protocol','fit-protocol.json','JSON','Features, labels, optimization, and the descriptive fitting protocol.'],
  ['Connected manifest','connected-manifest.csv','CSV','The retained manifest and connected identity groups behind the split.'],
  ['Antigen-context audit','antigen-context-audit.json','JSON','The audit of original antigen chains and antibody-free structural context.'],
  ['BepiPred comparison','bepipred-comparison.json','JSON','Official BepiPred-3.0 and PRINCE on the same corrected retrospective labels.'],
  ['BepiPred inference provenance','bepipred-inference-provenance.json','JSON','Upstream revision, inference settings, and source provenance.'],
  ['BepiPred verification','bepipred-verification.json','JSON','Verification of prediction completeness and residue mapping.'],
  ['PRINCE license','LICENSE.txt','TXT','MIT license for PRINCE. Third-party data and dependencies retain their own terms.'],
];
export default function ResourceLibrary(){const [query,setQuery]=useState('');const matches=resources.filter(r=>r.join(' ').toLowerCase().includes(query.trim().toLowerCase()));return <><div className="resource-tools"><label className="search-field"><span aria-hidden="true">⌕</span><span className="sr-only">Search resources</span><input type="search" placeholder="Find an artifact…" value={query} onChange={e=>setQuery(e.target.value)}/></label><span role="status">{matches.length} / {resources.length} ARTIFACTS</span></div><div className="resource-list">{matches.map(([name,file,format,description])=><a className="resource-row" key={file} href={`/prince/${file}`} download><span className="resource-num">{String(resources.findIndex(r=>r[1]===file)+1).padStart(2,'0')}</span><div><h3>{name}</h3><p>{description}</p></div><span className="resource-format">{format} / ↓</span><span className="download-arrow" aria-hidden="true">↘</span></a>)}{matches.length===0&&<p className="resource-empty">No artifacts match “{query}”. Try “model”, “site”, or “BepiPred”.</p>}</div></>;}
