import argparse
import json
import sys
from pathlib import Path

from .adapters import LocalModelAdapter
from .core import Failure, read_json, write_json
from .environment import inventory
from .media import MediaTools
from .ppt import parse_pptx, render_powerpoint
from .preflight import preflight


def setup(config):
    tools = config.get("tools", {})
    def locate(name):
        if tools.get(name):
            return tools[name]
        paths = list(Path(".tools/ffmpeg").glob(f"*/bin/{name}.exe"))
        return str(paths[0].resolve()) if paths else name
    policy = config.get("quality_policy", {})
    media = MediaTools(locate("ffmpeg"), locate("ffprobe"), **policy)
    storage = config.get("storage", "storage/m1")
    adapters = {role: LocalModelAdapter(role, config.get("models", {}).get(role), media, storage)
                for role in ["tts", "photo", "video"]}
    return media, adapters, storage


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Real M1 validation and blocking preflight")
    p.add_argument("--config", default="config/m1.example.json")
    sub = p.add_subparsers(dest="command", required=True)
    env = sub.add_parser("inventory")
    env.add_argument("--output", required=True)
    caps = sub.add_parser("capabilities")
    caps.add_argument("--output", required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("--manifest", required=True)
    pre.add_argument("--output", required=True)
    ppt = sub.add_parser("ppt")
    ppt.add_argument("input")
    ppt.add_argument("--output", required=True)
    ppt.add_argument("--render", action="store_true")
    probe = sub.add_parser("media")
    probe.add_argument("input")
    probe.add_argument("--kind", choices=["audio", "video", "photo"], required=True)
    probe.add_argument("--output", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--role", choices=["tts", "photo", "video"], required=True)
    gen.add_argument("--request", required=True)
    status = sub.add_parser("status")
    status.add_argument("--role", choices=["tts", "photo", "video"], required=True)
    status.add_argument("request_id")
    args = p.parse_args()
    try:
        config = read_json(args.config)
        media, adapters, storage = setup(config)
        if args.command == "inventory":
            result = inventory(config)
        elif args.command == "capabilities":
            result = {"models": {role: {"capabilities": a.capabilities(), "health": a.health()}
                                 for role, a in adapters.items()}}
        elif args.command == "preflight":
            result = preflight(read_json(args.manifest), adapters, media, storage, config.get("limits_mb"), config.get("max_ppt_pages", 50))
        elif args.command == "ppt":
            result = parse_pptx(args.input, Path(args.output) / "parsed", config.get("max_ppt_pages", 50))
            if args.render:
                render = render_powerpoint(args.input, Path(args.output) / "rendered")
                if render["page_count"] != result["page_count"]:
                    raise Failure("RUN_FAILED", "Parsed/rendered page count differs", args.input)
                result = {"parsed_pages": result["page_count"], "rendered_pages": render["page_count"],
                          "visual_review": "pending", "quality_passed": False}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        elif args.command == "media":
            result = media.inspect(args.input, args.kind)
        elif args.command == "generate":
            result = adapters[args.role].generate(read_json(args.request))
        else:
            result = adapters[args.role].status(args.request_id)
        if hasattr(args, "output"):
            write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get("ready") is False or result.get("state") == "failed" else 0
    except Failure as exc:
        result = {"success": False, "error": exc.record()}
    except (ValueError, KeyError, OSError) as exc:
        result = {"success": False, "error": {"code": "SERVICE_CONFIG_MISSING", "message": "Invalid or missing config/input file", "detail": type(exc).__name__}}
    if hasattr(args, "output"):
        write_json(Path(args.output) / "error.json" if args.command == "ppt" else args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2


if __name__ == "__main__":
    sys.exit(main())
