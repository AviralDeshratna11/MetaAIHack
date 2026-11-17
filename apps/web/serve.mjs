// Start Next on a loopback port that can actually be bound.
// Windows reserves shifting port ranges for Hyper-V/Docker; the usual port 53000 is
// sometimes inside one and fails with EACCES. Set WEB_PORT to choose a port; otherwise
// the first bindable port from a short list is used and printed.
import { createServer } from 'node:net';
import { spawn } from 'node:child_process';

const mode = process.argv[2] === 'dev' ? 'dev' : 'start';
const host = '127.0.0.1';
const wanted = process.env.WEB_PORT ? [Number(process.env.WEB_PORT)] : [53000, 3210, 3211, 3212, 8310];

function bindable(port) {
  return new Promise(resolve => {
    const probe = createServer();
    probe.once('error', error => resolve(error.code));
    probe.listen(port, host, () => probe.close(() => resolve(null)));
  });
}

let chosen = null;
for (const port of wanted) {
  const problem = await bindable(port);
  if (!problem) { chosen = port; break; }
  console.error(`Port ${port} cannot be used (${problem === 'EACCES' ? 'reserved by Windows' : problem}).`);
}
if (chosen === null) {
  console.error('No usable port. Set WEB_PORT to a free loopback port.');
  process.exit(1);
}
console.log(`Web app: http://${host}:${chosen}`);
const next = spawn(process.execPath, ['../../node_modules/next/dist/bin/next', mode, '--hostname', host, '--port', String(chosen)], { stdio: 'inherit' });
next.on('exit', code => process.exit(code ?? 1));
