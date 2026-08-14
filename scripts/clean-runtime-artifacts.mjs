import { existsSync, rmSync } from 'node:fs';
import path from 'node:path';

const runtimeDirs = ['.next', '.next-playwright'];
const projectRoot = process.cwd();

for (const dir of runtimeDirs) {
  const target = path.join(projectRoot, dir);
  if (!existsSync(target)) {
    continue;
  }

  rmSync(target, { recursive: true, force: true });
  console.log(`removed ${dir}`);
}
