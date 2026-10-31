"""
Generate SYNTHETIC slop reports for evaluation (task C3).

  python scripts/gen_slop.py --target curl --n 10 --out datasets/slop_synth

For each report: pull real identifiers from the target's source tree (inside the sandbox), ask the model for a
false-but-plausible report using one failure mode, and write datasets/<out>/<id>/report.md with label: slop.
Ground truth (failure_mode, cited_symbols) is stored in meta.json next to it — never shown to the triage models.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import yaml
from dotenv import load_dotenv

from repro.llm import LLM
from repro.prompts import load_prompt
from repro.sandbox import Sandbox
from repro.schemas import Target

MODES = ["hallucinated_symbol", "wrong_mechanism", "theoretical_only", "fake_poc", "misread_quote"]


def real_identifiers(sb: Sandbox, k: int = 60) -> tuple[list[str], list[str]]:
    src = sb.target.src_dir
    fns = sb.exec(f"grep -rhoE --include=*.c '^[a-zA-Z_][a-zA-Z0-9_ \\*]*\\b([A-Z][A-Za-z0-9_]{{4,}})\\(' {src} "
                  "| grep -oE '[A-Za-z0-9_]+\\($' | tr -d '(' | sort -u | shuf -n 400", timeout=120, workdir="/").stdout.split()
    files = sb.exec(f"cd {src} && git ls-files '*.c' 2>/dev/null | shuf -n 60 || find . -name '*.c' | shuf -n 60",
                    timeout=60, workdir="/").stdout.split()
    return random.sample(fns, min(k, len(fns))), files


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--out", default="datasets/slop_synth")
    a = ap.parse_args()

    tcfg = yaml.safe_load(Path("config/targets.yaml").read_text())[a.target]
    target = Target(**tcfg)
    llm = LLM.cheap()   # bulk data generation on Baseten (falls back to Muse Spark if not configured)
    with Sandbox(target) as sb:
        fns, files = real_identifiers(sb)
    for i in range(a.n):
        mode = MODES[i % len(MODES)]
        user = (f"Project: {target.project}\nFailure mode: {mode}\n"
                f"Real functions: {', '.join(random.sample(fns, min(25, len(fns))))}\n"
                f"Real files: {', '.join(random.sample(files, min(15, len(files))))}")
        resp = llm.chat([{"role": "system", "content": load_prompt("slop_generator")},
                         {"role": "user", "content": user}],
                        response_format={"type": "json_object"}, temperature=0.9, stage="note")
        data = json.loads(resp.choices[0].message.content)
        rid = f"slop-{target.project}-{i:03d}"
        d = Path(a.out) / rid
        d.mkdir(parents=True, exist_ok=True)
        fm = {"id": rid, "title": data["title"], "source": "synthetic", "label": "slop", "target": tcfg}
        (d / "report.md").write_text("---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n" + data["body"])
        (d / "meta.json").write_text(json.dumps({"failure_mode": mode, "cited": data.get("cited_symbols", [])}, indent=2))
        print("wrote", d, mode)
    print(f"model {llm.model}: {llm.usage.calls} calls, ${llm.usage.cost_usd:.3f}")


if __name__ == "__main__":
    main()
