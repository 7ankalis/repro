"""Pull every docker image referenced by config/targets.yaml and datasets/**/report.md front matter."""
import subprocess
import sys
from pathlib import Path

import yaml

images: set[str] = set()
for _name, t in (yaml.safe_load(Path("config/targets.yaml").read_text()) or {}).items():
    for k in ("image", "fixed_image"):
        if t.get(k) and "REPLACE" not in t[k] and not t[k].startswith("repro/"):
            images.add(t[k])
for rp in Path("datasets").rglob("report.md"):
    fm = rp.read_text().split("---", 2)[1]
    tgt = (yaml.safe_load(fm) or {}).get("target", {})
    for k in ("image", "fixed_image"):
        if tgt.get(k) and "REPLACE" not in tgt[k] and not tgt[k].startswith("repro/"):
            images.add(tgt[k])
print(f"{len(images)} images to pull")
failed = []
for img in sorted(images):
    print("→", img, flush=True)
    if subprocess.run(["docker", "pull", "-q", img]).returncode != 0:
        failed.append(img)
print("failed:", failed or "none")
sys.exit(1 if failed else 0)
