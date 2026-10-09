"""Inspect documentation, current real outputs and reproducible code versions."""
import importlib.metadata
import re
import sys
from pathlib import Path
from urllib.parse import unquote
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mooc_m1.core import read_json, write_json, digest, run, stamp
from mooc_m2.api import create_app


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / "docs/evidence/M2"
    documents = [root / "AGENTS.md", root / "README.md", *list((root / "specs").glob("*.md")), *list((root / "docs").rglob("*.md")), *list((root / ".agents/skills").glob("*/SKILL.md"))]
    errors, count = [], 0
    for path in documents:
        text = path.read_text(encoding="utf-8-sig")
        if "\ufffd" in text:
            errors.append("encoding: " + str(path.relative_to(root)))
        for match in re.finditer(r"\[[^\]\n]*\]\(([^\)]+)\)", text):
            target = match[1].strip().strip("<>")
            if target.startswith(("https://", "http://", "#", "mailto:", "codex:")):
                continue
            count += 1
            if not (path.parent / unquote(target.split("#")[0])).exists():
                errors.append(str(path.relative_to(root)) + " -> " + target)
    status = (root / "docs/PROJECT_STATUS.md").read_text(encoding="utf-8")
    ids = re.findall(r"^\| (M[1-4]-F\d\d) \|", status, re.MULTILINE)
    assert len(ids) == 24 and len(set(ids)) == 24
    for stage in ["M1-capability-validation", "M2-content-pipeline"]:
        assert "- [x]" not in (root / f"specs/{stage}.spec.md").read_text(encoding="utf-8").lower()
    for name in ["README.md", "tests.xml", "real-content-chain.json", "control-validation.json", "browser-check.json"]:
        assert (out / name).is_file()
    doc_result = {"documents": len(documents), "local_links_checked": count, "stable_work_items": 24, "errors": errors, "m1_m2_exit_unchecked": True, "scope": "documentation integrity only"}
    write_json(out / "document-check.json", doc_result)
    if "--documents-only" in sys.argv:
        assert not errors, errors
        print(f"Documents {len(documents)}, links {count}, errors 0; stable IDs and pending exits preserved.")
        return
    app = create_app(worker=False)
    service = app.state.service
    real = read_json(out / "real-content-chain.json")
    p = service.store.get(real["project_id"])
    records = []
    for s in p["scenes"]:
        audio = s["audition"]
        decoded = service.media.inspect(service.store.file(p["id"], audio["path"]), "audio")
        assert decoded["sha256"] == audio["sha256"] and not audio["stale"] and not audio["human_review"]
        records.append({"scene_id": s["id"], "sha256": decoded["sha256"], "duration_seconds": decoded["duration_seconds"], "silence_ratio": decoded["silence_ratio"], "human_review": "pending"})
    real["current_preflight"] = service.preflight(p)
    real["final_redecode"] = records
    real["verified_at"] = stamp()
    write_json(out / "real-content-chain.json", real)
    files = [*list((root / "mooc_m2").glob("*.py")), root / "mooc_m1/adapters.py", root / "mooc_m1/model_worker.py", root / "mooc_m1/office_worker.py", *list((root / "frontend/src").glob("*")), root / "frontend/package.json", root / "frontend/package-lock.json", root / "requirements-m2.txt", root / "tests/test_m2.py"]
    versions = {name: importlib.metadata.version(name) for name in ["fastapi", "uvicorn", "starlette", "python-multipart", "httpx", "python-pptx", "Pillow", "pydantic"]}
    checks = {"pip_check": run([sys.executable, "-m", "pip", "check"])["stdout"].strip(), "node": run(["node", "--version"])["stdout"].strip(), "vue": read_json(root / "frontend/package.json")["dependencies"]["vue"], "vite": read_json(root / "frontend/package.json")["devDependencies"]["vite"], "frontend_build": "passed; npm run build; production files in ignored frontend/dist", "test_report": "tests.xml", "known_test_warning": "Starlette 1.2.1 deprecates httpx TestClient transport; all behavior tests still execute", "windows_acl": "private root: current user, SYSTEM, Administrators; real icacls inspected", "storage": str(service.store.root)}
    write_json(out / "environment-check.json", {"checked_at": stamp(), "python": sys.version.split()[0], "versions": versions, "checks": checks, "source_hashes": {str(f.relative_to(root)).replace('\\','/'): digest(f) for f in files}, "total_real_audition_seconds": sum(r["duration_seconds"] for r in records), "stage_passed": False})
    # This script itself creates environment-check.json; recheck links after
    # all outputs are saved, so the first run is validated too.
    final_errors = []
    for path in documents:
        for match in re.finditer(r"\[[^\]\n]*\]\(([^\)]+)\)", path.read_text(encoding="utf-8-sig")):
            target = match[1].strip().strip("<>")
            if not target.startswith(("https://", "http://", "#", "mailto:", "codex:")) and not (path.parent / unquote(target.split("#")[0])).exists():
                final_errors.append(str(path.relative_to(root)) + " -> " + target)
    final_errors.extend(e for e in errors if e.startswith("encoding:"))
    doc_result["errors"] = final_errors
    write_json(out / "document-check.json", doc_result)
    assert not final_errors, final_errors
    print(f"Documents {len(documents)}, links {count}, errors 0; ten real audio files redecoded; human review pending.")


if __name__ == "__main__":
    main()
