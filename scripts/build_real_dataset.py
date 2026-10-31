"""
Build REAL reports from ARVO (task C1/C2).

  python scripts/build_real_dataset.py --ids 42487096 ... --mode with_poc --out datasets/real

Steps per ARVO id (verify each assumption on day 1 — see docs/VERIFY_FIRST.md):
  1. Metadata: project, crash type, fuzz target, fix commit. Source: ARVO-Meta release files (format: inspect first),
     or derive from the image itself: `docker run --rm --entrypoint sh n132/arvo:<id>-vul -c 'cat $(which arvo)'`
     shows the reproduce script → fuzz target path + PoC path.
  2. Ground-truth crash: run `arvo` ONCE yourself (not the agent) in the -vul image and save the sanitizer output to
     datasets/real/<id>/ground_truth.txt (eval only; never given to the models). Parse it with repro.sanitizer to get
     the crashing function/file for the report writer.
  3. PoC bytes (mode=with_poc): copy the PoC file out of the image (`docker cp`) into attachments/poc.bin.
  4. Report text: prompts/report_from_arvo.md with {project, function, file, bug type, fuzz target, mode}.
  5. Write report.md with label: real and target {image: -vul, fixed_image: -fix, src_dir, build_cmd: arvo compile}.

Sanity check before adding to the set: the PoC must crash on -vul and NOT crash on -fix.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import yaml
from dotenv import load_dotenv

from repro import sanitizer
from repro.llm import LLM
from repro.prompts import load_prompt


def sh(img: str, cmd: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "bash", img, "-lc", cmd],
                          capture_output=True, text=True, timeout=timeout)


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="+", required=True)
    ap.add_argument("--mode", choices=["with_poc", "text_only"], default="with_poc")
    ap.add_argument("--out", default="datasets/real")
    ap.add_argument("--src-dir", default=None, help="override /src/<project>")
    a = ap.parse_args()
    llm = LLM.cheap()   # bulk data generation on Baseten (falls back to Muse Spark if not configured)

    for aid in a.ids:
        vul, fix = f"n132/arvo:{aid}-vul", f"n132/arvo:{aid}-fix"
        d = Path(a.out) / f"arvo-{aid}-{a.mode}"
        d.mkdir(parents=True, exist_ok=True)

        script = sh(vul, "cat $(which arvo)").stdout
        (d / "arvo_script.txt").write_text(script)            # inspect: fuzz target + PoC path live here

        gt = sh(vul, "arvo 2>&1 | tail -200")
        rep = sanitizer.parse(gt.stdout + gt.stderr)
        if not rep:
            print(f"[skip] {aid}: no sanitizer output from arvo on -vul")
            continue
        fixed = sh(fix, "arvo 2>&1 | tail -200")
        if sanitizer.parse(fixed.stdout + fixed.stderr):
            print(f"[skip] {aid}: still crashes on -fix")
            continue
        (d / "ground_truth.txt").write_text(rep.raw)
        top = rep.top_project_frames(1)[0]
        project = (top.file or "/src/unknown/").split("/")[2] if top.file and top.file.startswith("/src/") else "unknown"

        # TODO(C1): extract PoC path from arvo_script.txt (e.g. /tmp/poc) and docker cp it for with_poc mode.
        if a.mode == "with_poc":
            (d / "attachments").mkdir(exist_ok=True)
            # cid = docker create vul ; docker cp cid:<poc_path> d/attachments/poc.bin ; docker rm cid

        user = json.dumps({"project": project, "function": top.function, "file": top.file,
                           "bug_type": rep.error_type, "mode": a.mode,
                           "fuzz_target": "see arvo script", "fix_description": "unknown (optional)"})
        resp = llm.chat([{"role": "system", "content": load_prompt("report_from_arvo")},
                         {"role": "user", "content": user}],
                        response_format={"type": "json_object"}, temperature=0.4, stage="note")
        data = json.loads(resp.choices[0].message.content)
        fm = {"id": d.name, "title": data["title"], "source": "synthetic", "label": "real",
              "target": {"project": project, "image": vul, "fixed_image": fix,
                         "src_dir": a.src_dir or f"/src/{project}", "build_cmd": "arvo compile",
                         "repro_cmd": "arvo", "test_cmd": None}}
        (d / "report.md").write_text("---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n" + data["body"])
        print("wrote", d)
    print(f"model {llm.model}: {llm.usage.calls} calls, ${llm.usage.cost_usd:.3f}")


if __name__ == "__main__":
    main()
