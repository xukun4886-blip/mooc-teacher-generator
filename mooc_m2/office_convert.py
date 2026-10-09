"""Legacy PPT conversion reuses the M1 isolated, macro-disabled Office owner."""
import sys
from pathlib import Path
from mooc_m1.office_worker import main

# Conversion is integrated with M1's process ownership code; see office_worker.
if __name__ == "__main__":
    from mooc_m1.core import write_json
    output = Path(sys.argv[2]).resolve()
    request = output.with_suffix(".conversion.json")
    write_json(request, {"input": str(Path(sys.argv[1]).resolve()), "output": str(output.parent / "legacy-preview"), "width": 1920, "convert_to": str(output)})
    sys.argv = [sys.argv[0], str(request)]
    main()
