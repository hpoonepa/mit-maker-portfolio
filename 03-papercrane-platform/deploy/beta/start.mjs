import { spawn } from 'node:child_process';
import { once } from 'node:events';
import net from 'node:net';

const children = [];
let stopping = false;
function start(name, command, args, cwd = '/app') {
  const child = spawn(command, args, { cwd, env: process.env, stdio: 'inherit' });
  children.push({ name, child });
  child.on('error', error => { console.error(`${name}: ${error.message}`); void stop(1); });
  child.on('exit', (code, signal) => {
    if (!stopping) { console.error(`${name} exited (${code ?? signal})`); void stop(1); }
  });
  return child;
}
async function terminate(child, timeout = 35000) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  const exited = once(child, 'exit').catch(() => {});
  child.kill('SIGTERM');
  const timer = setTimeout(() => child.kill('SIGKILL'), timeout);
  timer.unref();
  await exited;
  clearTimeout(timer);
}
async function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  // Keep Redis available while the worker stops accepting jobs and drains.
  await Promise.all(children.filter(x => x.name !== 'redis').map(x => terminate(x.child)));
  await Promise.all(children.filter(x => x.name === 'redis').map(x => terminate(x.child, 5000)));
  process.exit(code);
}
process.on('SIGTERM', () => void stop());
process.on('SIGINT', () => void stop());
start('redis', 'redis-server', ['/app/deploy/beta/redis.conf']);
let ready = false;
for (let attempt = 0; attempt < 60 && !stopping; attempt++) {
  ready = await new Promise(resolve => {
    const socket = net.connect(6379, '127.0.0.1');
    const finish = value => { socket.destroy(); resolve(value); };
    socket.setTimeout(500, () => finish(false));
    socket.once('connect', () => finish(true));
    socket.once('error', () => finish(false));
  });
  if (ready) break;
  await new Promise(resolve => setTimeout(resolve, 200));
}
if (!ready || stopping) await stop(1);
else {
  start('api', 'node', ['--import', 'tsx', 'src/server.ts'], '/app/apps/api');
  start('worker', 'node', ['--import', 'tsx', 'src/server.ts'], '/app/apps/worker');
}
