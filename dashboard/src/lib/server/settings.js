import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

const PROGRAM_ROOT = process.cwd();

export function loadSettings() {
    const custom = path.join(PROGRAM_ROOT, 'config', 'settings.json');
    const fallback = path.join(PROGRAM_ROOT, 'config', 'settings.example.json');
    const file = existsSync(custom) ? custom : fallback;
    const settings = JSON.parse(readFileSync(file, 'utf-8'));
    const vault = settings.vault ?? {};
    if (vault.local_path) {
        vault.local_path = path.resolve(PROGRAM_ROOT, vault.local_path);
    }
    if (vault.epassport_path) {
        vault.epassport_path = path.resolve(PROGRAM_ROOT, vault.epassport_path);
    }
    return settings;
}
