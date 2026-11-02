import { useState } from 'react';
import evaluation from '../../public/prince/site-uncertainty.json';
type Metric = 'majority_hit' | 'half_epitope_recovery';
type K = '1' | '3' | '5' | '10';
const percent=(n:number)=>(n*100).toFixed(2)+'%';
export default function BenchmarkExplorer(){
  const [metric,setMetric]=useState<Metric>('majority_hit');
  const [k,setK]=useState<K>('10');
  const fitted=evaluation.summary.fitted[metric][k];
  const baseline=evaluation.summary.exposure_only[metric][k];
  const difference=evaluation.paired_differences.fitted_minus_exposure_only[metric][k];
  return <div className="benchmark-explorer">
    <div className="benchmark-controls"><div className="segmented" aria-label="Evaluation metric"><button aria-pressed={metric==='majority_hit'} onClick={()=>setMetric('majority_hit')}>Majority-patch hit</button><button aria-pressed={metric==='half_epitope_recovery'} onClick={()=>setMetric('half_epitope_recovery')}>Half-epitope recovery</button></div><label>Sites considered<select aria-label="Sites considered" value={k} onChange={e=>setK(e.target.value as K)}>{['1','3','5','10'].map(value=><option key={value} value={value}>Top {value}</option>)}</select></label></div>
    <div aria-live="polite" aria-atomic="true">
      <div className="chart-row"><span>PRINCE fitted</span><div className="chart-track"><div className="chart-fill" style={{width:`${fitted.instance_fraction*100}%`}}/></div><strong>{fitted.hits}<small> / 110</small></strong></div>
      <div className="chart-row baseline"><span>Exposure only</span><div className="chart-track"><div className="chart-fill" style={{width:`${baseline.instance_fraction*100}%`}}/></div><strong>{baseline.hits}<small> / 110</small></strong></div>
      <div className="chart-axis"><span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div>
      <p className="benchmark-definition">{metric==='majority_hit'?evaluation.majority_hit_definition:evaluation.half_epitope_recovery_definition}. Bars show the fraction of 110 interfaces with a qualifying top-{k} patch.</p>
      <div className="benchmark-detail"><div><strong>Component-macro rate · PRINCE</strong><p>{percent(fitted.cluster_macro)} · 95% CI {fitted.cluster_macro_ci95.map(percent).join('–')}<br/>Averaged across 34 identity components.</p></div><div><strong>Paired difference vs exposure</strong><p>{(difference.cluster_macro_difference*100).toFixed(2)} percentage points<br/>95% CI {difference.paired_cluster_bootstrap_ci95.map(n=>(n*100).toFixed(2)).join(' to ')} pp.</p></div></div>
    </div>
    <p className="research-note" style={{marginTop:20,marginBottom:0}}>The paired interval includes zero, so the difference from exposure alone remains uncertain. Component bootstrap: 2,000 replicates, seed 0.</p>
  </div>;
}
