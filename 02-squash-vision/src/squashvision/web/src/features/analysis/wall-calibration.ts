import type { Point, WallCalibration } from "./shot-model";
export function validWallCalibration(c: WallCalibration): boolean {
  if (c.points.length !== 4 || ![.43,.48].includes(c.tinHeightM) || c.points.some(p=>p.length !== 2 || p.some(v=>!Number.isFinite(v)||v<0||v>1))) return false;
  const p=c.points;
  const cross=p.map((a,i)=>{const b=p[(i+1)%4],d=p[(i+2)%4];return (b[0]-a[0])*(d[1]-b[1])-(b[1]-a[1])*(d[0]-b[0]);});
  const area=Math.abs(p.reduce((s,a,i)=>s+a[0]*p[(i+1)%4][1]-a[1]*p[(i+1)%4][0],0))/2;
  return cross.every(v=>v < -1e-5) && area > .005 && p[0][0]<p[1][0] && p[3][0]<p[2][0] && p[0][1]>p[3][1] && p[1][1]>p[2][1];
}
export function projectWall(calibration: WallCalibration, point: Point): Point | null {
  if (!validWallCalibration(calibration) || point.some(v=>!Number.isFinite(v)||v<0||v>1)) return null;
  const targets:Point[]=[[0,0],[6.4,0],[6.4,1.78],[0,1.78]];
  const a:number[][]=[];
  calibration.points.forEach(([x,y],i)=>{const [u,v]=targets[i];a.push([x,y,1,0,0,0,-u*x,-u*y,u],[0,0,0,x,y,1,-v*x,-v*y,v]);});
  for(let col=0;col<8;col++) {
    let pivot=col;for(let row=col+1;row<8;row++)if(Math.abs(a[row][col])>Math.abs(a[pivot][col]))pivot=row;
    if(Math.abs(a[pivot][col])<1e-10)return null;
    [a[col],a[pivot]]=[a[pivot],a[col]];
    const divisor=a[col][col];for(let j=col;j<=8;j++)a[col][j]/=divisor;
    for(let row=0;row<8;row++)if(row!==col){const factor=a[row][col];for(let j=col;j<=8;j++)a[row][j]-=factor*a[col][j];}
  }
  const h=a.map(row=>row[8]),[x,y]=point,d=h[6]*x+h[7]*y+1;
  if(Math.abs(d)<1e-8)return null;
  const u=(h[0]*x+h[1]*y+h[2])/d,v=(h[3]*x+h[4]*y+h[5])/d;
  return Number.isFinite(u)&&Number.isFinite(v)&&u>=-1e-6&&u<=6.400001&&v>=-1e-6&&v<=4.57 ? [Math.max(0,Math.min(6.4,u)),Math.max(0,v)] : null;
}
