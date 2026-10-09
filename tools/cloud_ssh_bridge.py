"""Keep an authenticated local tunnel alive; passwords/tokens stay in memory.

Requires paramiko in a separate administration environment. The remote service
must bind 127.0.0.1:8787. This does not deploy or start model inference.
"""
from __future__ import annotations

import argparse
import getpass
import os
import select
import socketserver
import subprocess
import threading
from pathlib import Path

import paramiko


def tunnel(transport, port=8787):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                channel = transport.open_channel('direct-tcpip', ('127.0.0.1', 8787), self.request.getpeername())
            except paramiko.SSHException:
                return  # Caller gets connection failure, never an anonymous fallback.
            if channel is None:
                return
            try:
                while True:
                    ready, _, _ = select.select([self.request, channel], [], [], 10)
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        (channel if source is self.request else self.request).sendall(data)
            finally:
                channel.close()
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    server = Server(('127.0.0.1', port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--user', default='root')
    parser.add_argument('--local-port', type=int, default=8787)
    parser.add_argument('--workbench', help='Optional workstation repository; starts its local workbench with the in-memory API token')
    parser.add_argument('--workbench-port', type=int, default=8765)
    args = parser.parse_args()
    ssh = paramiko.SSHClient()
    ssh.load_host_keys(os.path.expanduser('~/.ssh/known_hosts'))
    # Reject unverified hosts. First connect with OpenSSH to establish its key.
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(args.host, port=args.port, username=args.user, password=getpass.getpass('SSH password: '),
                look_for_keys=False, allow_agent=False, timeout=15)
    ssh.get_transport().set_keepalive(20)
    server = tunnel(ssh.get_transport(), args.local_port)
    if args.workbench:
        # This private env file belongs to the designated single-tenant worker.
        with ssh.open_sftp() as sftp:
            with sftp.open('/root/autodl-tmp/mooc-cloud/runtime.env') as source:
                declaration = source.read().decode().strip()
        if not declaration.startswith('MOOC_CLOUD_TOKEN=') or len(declaration.split('=', 1)[1]) < 24:
            raise RuntimeError('Remote worker token declaration is invalid')
        root = Path(args.workbench).resolve()
        import socket
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', args.workbench_port)) == 0:
                raise RuntimeError('Local workbench is already running; stop it while idle before using this launcher')
        env = os.environ.copy()
        env['MOOC_CLOUD_TOKEN'] = declaration.split('=', 1)[1]
        log = (root / 'storage/m2/cloud-bridge-workbench.log').open('ab')
        subprocess.Popen([str(root / '.venv-m1/Scripts/python.exe'), '-m', 'mooc_m2', '--port', str(args.workbench_port), '--open'],
                         cwd=root, env=env, stdout=log, stderr=log, creationflags=0x08000000 if os.name == 'nt' else 0)
    print(f'SSH tunnel: http://127.0.0.1:{args.local_port} (private to this workstation)', flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
        ssh.close()
