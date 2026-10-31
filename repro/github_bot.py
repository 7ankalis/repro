"""
GitHub intake bot (task D4). Uses the `gh` CLI (no extra deps).

  python -m repro.github_bot --repo yourname/repro-demo --target curl --once
  python -m repro.github_bot --repo yourname/repro-demo --target curl --interval 30

Watches open issues labeled `security-report`, triages each once, comments the verdict, and labels
the issue `repro:VERIFIED` / `repro:INVALID_CLAIM` / ... Use a DEMO repo you own; never point this at a real
project's issue tracker without the maintainers' consent.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .pipeline import Config, triage
from .schemas import Report, Target

DONE_LABEL_PREFIX = "repro:"


def gh(*args: str) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}… failed: {r.stderr.strip()[:400]}")
    return r.stdout


def pending_issues(repo: str) -> list[dict]:
    issues = json.loads(gh("issue", "list", "--repo", repo, "--label", "security-report", "--state", "open",
                           "--json", "number,title,body,labels", "--limit", "50"))
    return [i for i in issues if not any(lb["name"].startswith(DONE_LABEL_PREFIX) for lb in i["labels"])]


def handle(repo: str, issue: dict, target: Target, cfg: Config) -> None:
    n = issue["number"]
    gh("issue", "comment", str(n), "--repo", repo, "--body",
       "🔬 **Repro** is verifying this report in an isolated sanitizer sandbox. Results in a few minutes.")
    report = Report(id=f"gh-{n}", title=issue["title"], body=issue["body"] or "", source="github", target=target)
    v = triage(report, cfg)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(v.maintainer_markdown)
        body_file = f.name
    gh("issue", "comment", str(n), "--repo", repo, "--body-file", body_file)
    label = f"{DONE_LABEL_PREFIX}{v.kind.value}"
    try:
        gh("label", "create", label, "--repo", repo, "--force", "--color",
           {"VERIFIED": "2da44e", "INVALID_CLAIM": "cf222e"}.get(v.kind.value, "8c959f"))
    except RuntimeError:
        pass
    gh("issue", "edit", str(n), "--repo", repo, "--add-label", label)
    print(f"#{n}: {v.kind.value} ({v.confidence:.2f})")


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.getenv("REPRO_GITHUB_REPO"), help="default: $REPRO_GITHUB_REPO")
    ap.add_argument("--target", required=True, help="key in config/targets.yaml")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--no-patch", action="store_true")
    a = ap.parse_args()
    if not a.repo:
        ap.error("--repo or REPRO_GITHUB_REPO is required")
    target = Target(**yaml.safe_load(Path("config/targets.yaml").read_text())[a.target])
    cfg = Config(do_patch=not a.no_patch)
    while True:
        for issue in pending_issues(a.repo):
            try:
                handle(a.repo, issue, target, cfg)
            except Exception as e:  # keep polling
                print(f"#{issue['number']} failed: {e}")
        if a.once:
            break
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
