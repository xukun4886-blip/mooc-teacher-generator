"""Explicit authorized single-clip benchmark, not a course generator."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mooc_cloud.adapter import RemotePhotoAdapter
from mooc_cloud.protocol import health, pinned, settings
from mooc_m1.core import read_json, write_json
from mooc_m1.media import MediaTools

parser = argparse.ArgumentParser()
parser.add_argument('--url', required=True)
parser.add_argument('--photo', required=True)
parser.add_argument('--audio', required=True)
parser.add_argument('--operation', required=True, help='Reuse to query same job; new ID means fresh inference')
parser.add_argument('--authorization-record', required=True)
parser.add_argument('--batch-size', type=int, choices=[1, 2, 4], default=1)
parser.add_argument('--ssh-loopback', action='store_true')
parser.add_argument('--token-env', default='MOOC_CLOUD_TOKEN')
parser.add_argument('--timeout', type=int, default=1800)
parser.add_argument('--allow-paid', action='store_true')
parser.add_argument('--max-cost', type=float, default=0)
parser.add_argument('--generation', type=int, default=1)
parser.add_argument('--output', required=True, help='New evidence JSON, never overwrite existing evidence')
args = parser.parse_args()
output = Path(args.output).resolve()
if output.exists():
    parser.error('Choose a new evidence path; previous runs must be retained')
root = Path(__file__).resolve().parents[1]
config = settings({'mode': 'cloud', 'url': args.url, 'token_env': args.token_env, 'batch_size': args.batch_size,
                   'allow_uploads': True, 'timeout_seconds': args.timeout, 'allow_paid': args.allow_paid,
                   'max_cost': args.max_cost}, loopback=args.ssh_loopback)
config = pinned(config, health(config))
local = read_json(root / 'config/m1.local.json')
tools = local.get('tools', {})
bundled = next((root / '.tools/ffmpeg').glob('*/bin/ffmpeg.exe'), None)
media = MediaTools(tools.get('ffmpeg', str(bundled) if bundled else 'ffmpeg'),
                   tools.get('ffprobe', str(bundled.with_name('ffprobe.exe')) if bundled else 'ffprobe'),
                   **local.get('quality_policy', {}))
audio = media.inspect(args.audio, 'audio', min_duration=.1)
if audio['duration_seconds'] > 120:
    parser.error('Only single clips <=120 seconds; full courses are outside this tool')
result = RemotePhotoAdapter(config, media, root / 'storage/cloud-samples').generate({
    'photo': str(Path(args.photo).resolve()), 'audio': str(Path(args.audio).resolve()),
    'authorized': True, 'authorization_record': args.authorization_record,
    'operation_id': args.operation, 'generation': args.generation})
write_json(output, result)
print(f"{result['state']}: {result['elapsed_seconds']:.3f}s; evidence {output}; quality_verified=false")
