"""Check repository documentation links, stable IDs and evidence file presence."""
import re
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mooc_m1.core import write_json


def main():
    root = Path(__file__).resolve().parents[1]
    files = [root / "AGENTS.md", root / "README.md"]
    files += list((root / "specs").glob("*.md")) + list((root / "docs").rglob("*.md"))
    files += list((root / ".agents/skills").glob("*/SKILL.md"))
    errors, checked = [], 0
    for path in files:
        text = path.read_text(encoding="utf-8-sig")
        if "\ufffd" in text:
            errors.append(f"Replacement character: {path.relative_to(root)}")
        for match in re.finditer(r"\[[^\]\n]*\]\(([^\)]+)\)", text):
            target = match.group(1).strip().strip("<>")
            if target.startswith(("https://", "http://", "#", "mailto:", "codex:")):
                continue
            target = unquote(target.split("#")[0])
            if not (path.parent / target).exists():
                errors.append(f"Missing link: {path.relative_to(root)} -> {target}")
            checked += 1
    state = (root / "docs/PROJECT_STATUS.md").read_text(encoding="utf-8")
    items = re.findall(r"^\| (M[1-4]-F\d\d) \|", state, re.MULTILINE)
    expected = {f"M{stage}-F{item:02d}" for stage in range(1, 5) for item in range(1, 7)}
    if len(items) != 24 or set(items) != expected:
        errors.append("Work-item IDs changed or duplicated")
    tracking = (root / "specs/TRACEABILITY.md").read_text(encoding="utf-8")
    for prefix, count in [("FR", 20), ("NFR", 8), ("AC", 18)]:
        found = set(re.findall(r"^\| (" + prefix + r"\d\d)\b", tracking, re.MULTILINE))
        if found != {f"{prefix}{i:02d}" for i in range(1, count + 1)}:
            errors.append(f"Traceability {prefix} IDs changed")
    spec = (root / "specs/M1-capability-validation.spec.md").read_text(encoding="utf-8")
    if "- [x]" in spec.lower():
        errors.append("M1 exit checkbox marked before native capability validation")
    evidence = root / "docs/evidence/M1"
    required = ["environment.json", "toolchain.json", "candidate-revisions.json", "capabilities.json",
                "preflight.json", "faults.json", "ppt-engineering.json", "tests.xml", "storage-access.json",
                "resource-baseline.json", "model-selection.md", "material-source.md"]
    for name in required:
        if not (evidence / name).is_file():
            errors.append(f"Missing evidence: {name}")
    result = {"documents": len(files), "local_links_checked": checked, "work_items": len(items),
              "fr": 20, "nfr": 8, "ac": 18, "errors": errors,
              "scope": "documentation integrity only, not M1 exit or product acceptance"}
    write_json(evidence / "document-check.json", result)
    print(result)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
