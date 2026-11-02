interface SpeedSample { speedMps: number; proxyTimestampUs: number | null; proxyEndTimestampUs: number | null }
/** Causal 5-reading median + 120 ms low-pass. No interpolation over missing video evidence. */
export function smoothSpeedSamples<T extends SpeedSample>(samples: T[], impacts: number[]): T[] {
  let history:number[]=[], filtered=0, previous:T|undefined;
  const times=[...impacts].sort((a,b)=>a-b); let impactIndex=0;
  return samples.map(sample=>{
    const t=sample.proxyTimestampUs;
    if(t===null){previous=undefined;history=[];return {...sample};}
    let crossed=false;
    while(impactIndex<times.length&&times[impactIndex]<=t){if(previous?.proxyTimestampUs!==null&&previous?.proxyTimestampUs!==undefined&&times[impactIndex]>previous.proxyTimestampUs)crossed=true;impactIndex++;}
    const continuous=previous?.proxyTimestampUs!==null&&previous?.proxyTimestampUs!==undefined&&previous.proxyEndTimestampUs!==null&&t>=previous.proxyTimestampUs&&t<=previous.proxyEndTimestampUs+1&&t-previous.proxyTimestampUs<=100_000;
    if(!continuous||crossed){history=[];filtered=sample.speedMps;}
    history.push(sample.speedMps);if(history.length>5)history.shift();
    const sorted=[...history].sort((a,b)=>a-b),median=(sorted[Math.floor((sorted.length-1)/2)]+sorted[Math.floor(sorted.length/2)])/2;
    if(continuous&&!crossed){const dt=t-previous!.proxyTimestampUs!;filtered+=(1-Math.exp(-dt/120_000))*(median-filtered);}
    previous=sample;
    return {...sample,speedMps:filtered};
  });
}
