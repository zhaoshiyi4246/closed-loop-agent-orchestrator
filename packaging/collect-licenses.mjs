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
// Enumerate the modules actually linked into this binary. `-m all` also walks
// test-only/transitive module graphs and can fetch unrelated uncached modules.
const modules = execFileSync(go, ['list', '-deps', '-f', '{{with .Module}}{{.Path}}|{{.Version}}|{{.Dir}}{{end}}', './cmd/ao'], {
  cwd: path.join(root, 'ao', 'backend'), encoding: 'utf8', windowsHide: true, timeout: 120_000,
  env: { ...process.env, GOWORK: 'off', GOTOOLCHAIN: 'local', GOFLAGS: '-mod=readonly' },
});
for (const line of new Set(modules.trim().split(/\r?\n/).filter(Boolean))) {
  const [name, version, dir] = line.split('|');
  if (dir) collect(dir, `${name}@${version}`, false);
}
writeFileSync(path.join(frontend, 'resources', 'third-party', 'DEPENDENCY-NOTICES.txt'), notices.join(''), 'utf8');
