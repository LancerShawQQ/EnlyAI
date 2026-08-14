import { mkdir, copyFile } from 'node:fs/promises';
import path from 'node:path';
import { build } from 'esbuild';

const repoRoot = process.cwd();
const distDir = process.env.NEXT_DIST_DIR || '.next';
const standaloneDir = path.join(repoRoot, distDir, 'standalone');

await mkdir(standaloneDir, { recursive: true });

await build({
  entryPoints: [path.join(repoRoot, 'lib', 'server', 'classroom-websocket.ts')],
  outfile: path.join(standaloneDir, 'classroom-websocket.cjs'),
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node20',
  external: ['better-sqlite3', 'sharp', '@napi-rs/canvas'],
  sourcemap: false,
  tsconfig: path.join(repoRoot, 'tsconfig.json'),
});

await copyFile(
  path.join(repoRoot, 'custom-server.mjs'),
  path.join(standaloneDir, 'custom-server.mjs'),
);

console.log('Bundled classroom WebSocket handler into .next/standalone');
