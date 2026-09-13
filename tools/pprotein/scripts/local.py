#!/usr/bin/env python3
"""Generate pprotein targets or hold SSH tunnels from the same inventory."""
import argparse
import json
import subprocess
import sys
import time


def configuration(inventory, hosts, seconds):
    targets, commands, used = [], [], set()
    for name in hosts:
        h = inventory['_meta']['hostvars'][name]
        forwards = []
        for kind, enabled, endpoint in (
            ('httplog', 'pprotein_collect_http', '/debug/log/httplog'),
            ('slowlog', 'pprotein_collect_sql', '/debug/log/slowlog'),
            ('pprof', 'pprotein_collect_go', '/debug/pprof/profile'),
        ):
            if not h.get(enabled, False):
                continue
            cpu = kind == 'pprof'
            local = int(h['pprotein_tunnel_go_port' if cpu else 'pprotein_tunnel_log_port'])
            remote = int(h.get('pprotein_go_port' if cpu else 'pprotein_agent_port', 19001 if cpu else 19000))
            if not (1024 <= local <= 65535 and 1024 <= remote <= 65535):
                raise ValueError('Invalid port')
            forward = f'127.0.0.1:{local}:127.0.0.1:{remote}'
            if forward not in forwards:
                if local in used:
                    raise ValueError(f'Duplicate local port {local}')
                used.add(local)
                forwards.append(forward)
            targets.append({'Type': kind, 'Label': f'{name}-{kind}',
                            'URL': f'http://127.0.0.1:{local}{endpoint}', 'Duration': seconds})
        if forwards:
            cmd = ['ssh', '-N', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
                   '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3']
            for forward in forwards:
                cmd += ['-L', forward]
            if 'ansible_user' in h:
                cmd += ['-l', str(h['ansible_user'])]
            if 'ansible_port' in h:
                cmd += ['-p', str(int(h['ansible_port']))]
            host = str(h.get('ansible_host', name))
            if host.startswith('-') or any(c.isspace() for c in host):
                raise ValueError('Invalid SSH host')
            cmd.append(host)
            commands.append(cmd)
    if not commands:
        raise ValueError('No enabled sources')
    return targets, commands


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['targets', 'tunnel'])
    p.add_argument('-i', '--inventory', required=True)
    p.add_argument('--hosts', required=True, help='Comma-separated inventory host names')
    p.add_argument('--seconds', type=int, default=60)
    a = p.parse_args()
    if a.seconds < 1:
        p.error('--seconds must be positive')
    raw = subprocess.check_output(['ansible-inventory', '-i', a.inventory, '--list'])
    targets, commands = configuration(json.loads(raw), a.hosts.split(','), a.seconds)
    if a.action == 'targets':
        print(json.dumps(targets, indent=2))
        return
    children = []
    try:
        for command in commands:
            children.append(subprocess.Popen(command))
        print('SSH tunnels running. Ctrl-C closes them. Remote service remains running.', flush=True)
        while True:
            for child in children:
                if child.poll() is not None:
                    raise RuntimeError('An SSH tunnel exited; closing all tunnels')
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    main()
