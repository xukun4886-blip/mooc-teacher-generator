"""Task-local pip with registry/environment proxy lookup disabled.

Uses HTTPS certificate verification. Does not change system proxy settings.
Run only inside the dedicated environment being prepared.
"""
import sys
import os
import hashlib
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlparse
from pip._vendor.requests.sessions import Session
from pip._vendor.requests import Response
from pip._vendor.urllib3.response import HTTPResponse
from pip._internal.cli.main import main

original = Session.__init__
original_send = Session.send

def direct(self, *args, **kwargs):
    original(self, *args, **kwargs)
    self.trust_env = False

Session.__init__ = direct

def send(self, request, **kwargs):
    # On this host Python downloads from files.pythonhosted.org are ~37 KB/s,
    # while Windows HTTPS transport is fast. Keep pip's resolver/hash checks.
    if request.method == 'GET' and urlparse(request.url).hostname in {'files.pythonhosted.org', 'pypi.org'}:
        cache = Path(__file__).resolve().parents[1] / '.tools/pypi-transfer'
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / hashlib.sha256(request.url.encode()).hexdigest()
        if not path.exists():
            part = path.with_suffix('.' + uuid.uuid4().hex + '.partial')
            env = os.environ.copy()
            env['M1_PYPI_URL'], env['M1_PYPI_TARGET'] = request.url, str(part)
            subprocess.run(['pwsh','-NoProfile','-NonInteractive','-Command',
                "$ErrorActionPreference='Stop'; Invoke-WebRequest -Uri $env:M1_PYPI_URL -OutFile $env:M1_PYPI_TARGET -TimeoutSec 120"],
                env=env, check=True, capture_output=True)
            try:
                if path.exists():
                    part.unlink()
                else:
                    part.replace(path)
            except OSError:
                if not path.is_file():
                    raise
                part.unlink(missing_ok=True)
        result = Response()
        result.status_code = 200
        result.url = request.url
        result.encoding = 'utf-8'
        result.headers['Content-Length'] = str(path.stat().st_size)
        if urlparse(request.url).hostname == 'pypi.org':
            result.headers['Content-Type'] = 'text/html; charset=utf-8'
        result.raw = HTTPResponse(body=path.open('rb'), status=200,
                                  headers=result.headers, preload_content=False)
        return result
    kwargs['proxies'] = {}
    return original_send(self, request, **kwargs)

Session.send = send
sys.exit(main(sys.argv[1:]))
