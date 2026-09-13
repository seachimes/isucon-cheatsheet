#!/usr/bin/env python3
"""Snapshot only this deployment's three files and its systemd state."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

BASE = Path('/var/backups/isucon-pprotein')
FILES = [Path('/opt/isucon-pprotein/agent'), Path('/opt/isucon-pprotein/agent.env'),
         Path('/etc/systemd/system/isucon-pprotein-agent.service')]
UNIT = 'isucon-pprotein-agent.service'


def systemctl(*args, check=True):
    p = subprocess.run(['systemctl', *args], text=True, capture_output=True)
    if check and p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    return p.stdout.strip()


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, data):
    temp = path.with_suffix('.tmp')
    with temp.open('w') as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


def snapshot(directory):
    directory.mkdir(parents=True, exist_ok=False)
    active = systemctl('is-active', UNIT, check=False)
    enabled = systemctl('is-enabled', UNIT, check=False)
    if active not in ('active', 'inactive', 'unknown') or enabled not in ('enabled', 'disabled', 'not-found', ''):
        raise RuntimeError('Unsupported initial service state; inspect before proceeding')
    records = []
    for index, path in enumerate(FILES):
        if path.is_symlink():
            raise RuntimeError(f'Refusing symlink: {path}')
        item = {'path': str(path), 'exists': path.exists()}
        if path.exists():
            stat = path.stat()
            saved = directory / str(index)
            shutil.copyfile(path, saved)
            item.update(mode=stat.st_mode & 0o7777, uid=stat.st_uid, gid=stat.st_gid, sha256=digest(saved))
            if digest(path) != item['sha256']:
                raise RuntimeError('Source changed during backup')
        records.append(item)
    write_json(directory / 'manifest.json', {'files': records, 'active': active, 'enabled': enabled})
    write_json(directory.parent / 'latest.json', {'id': directory.name})


def restore(directory):
    if (directory / 'restored').exists():
        print('already restored')
        return
    latest = json.loads((directory.parent / 'latest.json').read_text())
    if latest['id'] != directory.name:
        raise RuntimeError('Refusing an old snapshot; recover the latest change first')
    manifest = json.loads((directory / 'manifest.json').read_text())
    if [x['path'] for x in manifest['files']] != [str(x) for x in FILES]:
        raise RuntimeError('Unexpected restore paths')
    # Validate the entire backup before stopping anything.
    for index, item in enumerate(manifest['files']):
        if item['exists'] and digest(directory / str(index)) != item['sha256']:
            raise RuntimeError('Backup checksum mismatch')
    if FILES[-1].exists():
        systemctl('stop', UNIT)
        systemctl('disable', UNIT)
    for index, item in enumerate(manifest['files']):
        path = Path(item['path'])
        if item['exists']:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + '.restore-tmp')
            shutil.copyfile(directory / str(index), temp)
            os.chmod(temp, item['mode'])
            os.chown(temp, item['uid'], item['gid'])
            temp.replace(path)
        else:
            path.unlink(missing_ok=True)
    systemctl('daemon-reload')
    if manifest['enabled'] == 'enabled':
        systemctl('enable', UNIT)
    if manifest['active'] == 'active':
        systemctl('start', UNIT)
        systemctl('is-active', UNIT)
    (directory / 'restored').touch()


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('snapshot', 'restore'):
        raise SystemExit('usage: recovery.py snapshot|restore CHANGE_ID')
    change_id = sys.argv[2]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', change_id):
        raise SystemExit('invalid change ID')
    os.umask(0o077)
    directory = BASE / change_id
    (snapshot if sys.argv[1] == 'snapshot' else restore)(directory)
    print(json.dumps({'action': sys.argv[1], 'backup': str(directory)}))


if __name__ == '__main__':
    main()
