from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from PIL import Image
from lxml import etree

from .core import Failure, digest, run, write_json


def parse_pptx(path, output, max_pages=50):
    path, output = Path(path).resolve(), Path(output).resolve()
    try:
        with zipfile.ZipFile(path) as z:
            if "ppt/presentation.xml" not in z.namelist():
                raise ValueError("not a presentation package")
            if any(x.file_size > 200 * 1024 * 1024 for x in z.infolist()):
                raise ValueError("oversized package member")
        prs = Presentation(path)
    except Exception as exc:
        raise Failure("UNDECODABLE", "Invalid PPTX package", str(path)) from exc
    if not 1 <= len(prs.slides) <= max_pages:
        raise Failure("INPUT_INCOMPATIBLE", "Slide count exceeds configured range", str(path))
    source_hash = digest(path)
    pages = []
    for index, slide in enumerate(prs.slides, 1):
        xml_path = output / f"source-xml/slide-{index:03d}.xml"
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        xml_path.write_bytes(etree.tostring(slide._element, encoding="utf-8", xml_declaration=True))
        shapes, text, images, anomalies, fonts = [], [], [], [], set()
        def visit(collection):
            for shape in collection:
                item = {"id": shape.shape_id, "name": shape.name, "kind": str(shape.shape_type),
                        "bounds_emu": [shape.left, shape.top, shape.width, shape.height]}
                if shape.has_text_frame:
                    item["text"] = shape.text
                    text.append(shape.text)
                    for paragraph in shape.text_frame.paragraphs:
                        for chunk in paragraph.runs:
                            if chunk.font.name:
                                fonts.add(chunk.font.name)
                if shape.has_table:
                    item["table"] = [[c.text for c in row.cells] for row in shape.table.rows]
                    text.extend(c.text for row in shape.table.rows for c in row.cells)
                if shape.has_chart:
                    anomalies.append({"shape_id": shape.shape_id, "code": "CHART_REVIEW_REQUIRED"})
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    image = shape.image
                    h = __import__("hashlib").sha256(image.blob).hexdigest()
                    relative = f"images/{h}.{image.ext}"
                    target = output / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(image.blob)
                    images.append({"shape_id": shape.shape_id, "sha256": h, "path": relative})
                tags = {node.tag.rsplit("}", 1)[-1] for node in shape._element.iter()}
                if tags & {"oMath", "oMathPara"}:
                    anomalies.append({"shape_id": shape.shape_id, "code": "FORMULA_REVIEW_REQUIRED"})
                    item["equations_ooxml"] = [etree.tostring(node, encoding="unicode") for node in shape._element.iter()
                                               if node.tag.rsplit("}", 1)[-1] == "oMath"]
                if tags & {"videoFile", "audioFile", "media", "oleObj"}:
                    anomalies.append({"shape_id": shape.shape_id, "code": "EMBEDDED_MEDIA_REVIEW_REQUIRED"})
                shapes.append(item)
                if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                    visit(shape.shapes)
        visit(slide.shapes)
        relations = []
        for rel in slide.part.rels.values():
            if any(t in rel.reltype.lower() for t in ["image", "audio", "video", "oleobject", "media"]):
                relations.append({"id": rel.rId, "type": rel.reltype, "external": rel.is_external,
                                  "target": rel.target_ref})
        if not any(t.strip() for t in text) and images:
            anomalies.append({"code": "IMAGE_ONLY_PAGE", "message": "No inferred text or fabricated notes"})
        # Inherited/theme fonts require renderer review even if all explicit fonts are present.
        anomalies.append({"code": "FONT_REVIEW_REQUIRED", "explicit_fonts": sorted(fonts),
                          "message": "Check installed fonts, inherited fonts and rendered glyphs"})
        notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide and slide.notes_slide.notes_text_frame else ""
        pages.append({"source_page_id": f"{source_hash}:slide-{slide.slide_id}",
                      "source_index": index, "slide_id": slide.slide_id, "body": "\n".join(text),
                      "notes_original": notes, "images": images, "shapes": shapes,
                      "source_xml_path": f"source-xml/slide-{index:03d}.xml",
                      "media_relations": relations, "anomalies": anomalies})
    result = {"schema_version": "m1.ppt.v1", "source": str(path), "source_sha256": source_hash,
              "page_count": len(pages), "width_emu": prs.slide_width, "height_emu": prs.slide_height,
              "pages": pages, "rendered": False}
    write_json(output / "structure.json", result)
    return result


def render_powerpoint(path, output, timeout=180, width=1920):
    """Original slide export in an isolated COM process. Never redraw slide contents."""
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise Failure("INPUT_INCOMPATIBLE", "Render directory must be empty to avoid stale pages", str(output))
    output.mkdir(parents=True, exist_ok=True)
    request = output / "render-request.json"
    write_json(request, {"input": str(Path(path).resolve()), "output": str(output), "width": width})
    run([sys.executable, "-m", "mooc_m1.office_worker", request], timeout, log_path=output / "worker.log")
    report = json.loads((output / "render.json").read_text(encoding="utf-8"))
    for index, record in enumerate(report["pages"], 1):
        image = output / record["path"]
        with Image.open(image) as im:
            im.verify()
        if record["source_index"] != index:
            raise Failure("RUN_FAILED", "Renderer page order mismatch", str(image))
        record["sha256"] = digest(image)
    write_json(output / "render.json", report)
    return report
