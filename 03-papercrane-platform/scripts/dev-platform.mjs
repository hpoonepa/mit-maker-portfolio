// Start the local product stack, including durable Redis. Existing listeners
// are left alone; Ctrl-C stops only processes started by this launcher.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import net from 'node:net';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
process.loadEnvFile(path.join(root, '.env.local'));
const env = {
  ...process.env,
  NEXT_PUBLIC_APP_URL: 'http://localhost:4444',
  NEXT_PUBLIC_API_URL: 'http://localhost:3001',
  NEXT_PUBLIC_WEB_URL: 'http://localhost:4444',
  REDIS_URL: process.env.REDIS_URL || 'redis://127.0.0.1:6379',
  WORKER_DEV_MODE: 'false',
};
const children = [];
function stop() {
  for (const child of children) child.kill('SIGTERM');
}
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
function start(command, args, cwd = root, childEnv = env) {
  const child = spawn(command, args, { cwd, env: childEnv, stdio: 'inherit' });
  children.push(child);
  child.on('error', (error) => { console.error(error.message); process.exitCode = 1; stop(); });
  child.on('exit', (code, signal) => {
    if (code && !signal) { process.exitCode = code; stop(); }
  });
}
function listening(port, host = '127.0.0.1') {
  return new Promise((resolve) => {
    const socket = net.connect(port, host);
    const finish = (ok) => { socket.destroy(); resolve(ok); };
    socket.setTimeout(700, () => finish(false));
    socket.once('connect', () => finish(true));
    socket.once('error', () => finish(false));
  });
}
const redis = new URL(env.REDIS_URL);
if (!(await listening(Number(redis.port || 6379), redis.hostname))) {
  if (!['localhost', '127.0.0.1'].includes(redis.hostname)) {
    throw new Error('Configured remote Redis is unreachable; restore it before starting the platform.');
  }
  const dir = path.join(root, '.local/redis');
  mkdirSync(dir, { recursive: true });
  start('redis-server', ['--bind', '127.0.0.1', '--port', redis.port || '6379', '--protected-mode', 'yes', '--appendonly', 'yes', '--dir', dir]);
  for (let attempt = 0; attempt < 30; attempt++) {
    if (await listening(Number(redis.port || 6379))) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  if (!(await listening(Number(redis.port || 6379)))) { stop(); throw new Error('Redis failed to start.'); }
}
for (const [name, port, args] of [
  ['api', 3001, ['node', '--import', 'tsx', 'src/server.ts']],
  ['worker', 9090, ['node', '--import', 'tsx', 'src/server.ts']],
  ['app', 3002, ['next', 'dev', '--webpack', '-p', '3002']],
]) {
  if (await listening(port)) console.log(`${name}: port ${port} already in use; keeping the existing process.`);
  else start('pnpm', ['--filter', `@papercrane/${name}`, 'exec', ...args]);
}
const landing = path.resolve(root, '../papercrane-website/kriss-replica');
if (existsSync(path.join(landing, 'vite.config.mjs'))) {
  if (await listening(4444, 'localhost')) console.log('Website: port 4444 already in use; keeping the existing process.');
  // Do not pass the platform's database and provider credentials to Vite.
  else start('npm', ['run', 'dev'], landing, { PATH: process.env.PATH, HOME: process.env.HOME, TMPDIR: process.env.TMPDIR });
  console.log('Website + app: http://localhost:4444 (product: /app)');
} else console.log('Public website checkout not found at ../papercrane-website/kriss-replica');
console.log('Direct product app: http://localhost:3002/dashboard');
console.log('Health: http://localhost:3001/healthz and http://localhost:9090/healthz');
