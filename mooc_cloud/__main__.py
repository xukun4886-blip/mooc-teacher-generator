import argparse
from pathlib import Path

import uvicorn

from mooc_m1.core import read_json
from .server import create_app

parser = argparse.ArgumentParser(description='Independent serial SadTalker GPU worker')
parser.add_argument('--config', required=True)
parser.add_argument('--host', default='127.0.0.1')
parser.add_argument('--port', type=int, default=8787)
args = parser.parse_args()
config = read_json(Path(args.config).resolve())
uvicorn.run(create_app(config), host=args.host, port=args.port, workers=1)
