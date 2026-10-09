import argparse
import sys
import secrets
import webbrowser
from pathlib import Path
import uvicorn
from mooc_m1.core import read_json
from .api import create_app

parser = argparse.ArgumentParser()
parser.add_argument("--config", default="config/m2.local.json")
parser.add_argument("--port", type=int, default=8765)
parser.add_argument("--open", action="store_true", help="自动打开本机登录地址")
args = parser.parse_args()
sys.stdout.reconfigure(encoding="utf-8")
path = Path(args.config)
config = read_json(path if path.is_file() else "config/m2.example.json")
app = create_app(config)
app.state.launch_ticket = secrets.token_urlsafe(32)
app.state.launch_created = __import__("time").monotonic()
print(f"本地工作台：http://127.0.0.1:{args.port}/ （访问仍需本机会话）", flush=True)
if args.open:
    import threading
    threading.Timer(2, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}/#launch={app.state.launch_ticket}")).start()
uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
