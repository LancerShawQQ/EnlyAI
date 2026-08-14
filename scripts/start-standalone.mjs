import { cp, mkdir, rm } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import path from 'node:path';

const repoRoot = process.cwd();
const distDir = process.env.NEXT_DIST_DIR || '.next';
const standaloneDir = path.join(repoRoot, distDir, 'standalone');
const standaloneNextDir = path.join(standaloneDir, distDir);

await mkdir(standaloneNextDir, { recursive: true });
await cp(path.join(repoRoot, 'public'), path.join(standaloneDir, 'public'), {
  recursive: true,
  force: true,
});
await rm(path.join(standaloneNextDir, 'static'), { recursive: true, force: true });
await cp(path.join(repoRoot, distDir, 'static'), path.join(standaloneNextDir, 'static'), {
  recursive: true,
  force: true,
});
await cp(path.join(repoRoot, 'custom-server.mjs'), path.join(standaloneDir, 'custom-server.mjs'), {
  force: true,
});

const child = spawn(process.execPath, ['custom-server.mjs'], {
  cwd: standaloneDir,
  stdio: 'inherit',
  env: process.env,
});

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
