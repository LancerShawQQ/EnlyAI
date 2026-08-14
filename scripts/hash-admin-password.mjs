import bcrypt from 'bcryptjs';
import { createInterface } from 'node:readline/promises';
import { stdin as input, stdout as output } from 'node:process';

const SALT_ROUNDS = 12;

const rl = createInterface({ input, output });

try {
  const password = await rl.question('Admin password: ');
  if (!password || password.length < 12) {
    console.error('Password must be at least 12 characters.');
    process.exitCode = 1;
  } else {
    const hash = await bcrypt.hash(password, SALT_ROUNDS);
    console.log(`ADMIN_PASSWORD_HASH=${hash}`);
  }
} finally {
  rl.close();
}
