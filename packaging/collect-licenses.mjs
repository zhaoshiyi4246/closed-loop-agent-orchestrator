// Build-only notice collection. No user files or installed AO data are read.
import { readdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
const [root, go] = process.argv.slice(2);
const frontend = path.join(root, 'ao', 'frontend');
const notices = [];
function collect(directory, label, recursive) {
  if (!existsSync(directory)) return;
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (entry.isSymbolicLink()) continue;
    const file = path.join(directory, entry.name);
    if (entry.isDirectory() && recursive) collect(file, `${label}/${entry.name}`, true);
    else if (entry.isFile() && /^(licen[cs]e|copying|notice)([.-]|$)/i.test(entry.name)) {
      notices.push(`\n===== ${label}/${entry.name} =====\n${readFileSync(file, 'utf8')}\n`);
    }
  }
}
collect(path.join(frontend, 'node_modules'), 'npm', true);
const modules = execFileSync(go, ['list', '-m', '-f', '{{.Path}}|{{.Version}}|{{.Dir}}', 'all'], {
  cwd: path.join(root, 'ao', 'backend'), encoding: 'utf8', windowsHide: true,
});
for (const line of modules.trim().split(/\r?\n/)) {
  const [name, version, dir] = line.split('|');
  if (dir) collect(dir, `${name}@${version}`, false);
}
writeFileSync(path.join(frontend, 'resources', 'third-party', 'DEPENDENCY-NOTICES.txt'), notices.join(''), 'utf8');
