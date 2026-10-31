"""Pull ARVO -vul/-fix image pairs for a list of ids, stopping before the disk fills.

    python scripts/pull_arvo.py --ids 15373 21176 ... --min-free-gb 25

ARVO images are large and share base layers, so free space is checked before every
pull and the run stops cleanly once it would drop below --min-free-gb. Ids whose pair
pulls successfully are printed as PULLED (ready for build_real_dataset.py --validate-only).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys


def free_gb(path: str = "/") -> float:
    return shutil.disk_usage(path).free / 1e9


def pull(image: str) -> bool:
    print("→", image, flush=True)
    return subprocess.run(["docker", "pull", "-q", image]).returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ids", nargs="+", required=True)
    ap.add_argument("--min-free-gb", type=float, default=25.0)
    args = ap.parse_args()
    pulled, failed, skipped = [], [], []
    for aid in dict.fromkeys(args.ids):
        if free_gb() < args.min_free_gb:
            print(f"[stop] free disk {free_gb():.0f}GB < {args.min_free_gb:.0f}GB; "
                  f"not pulling {aid}", flush=True)
            skipped.append(aid)
            continue
        vul, fix = f"n132/arvo:{aid}-vul", f"n132/arvo:{aid}-fix"
        if pull(vul) and pull(fix):
            pulled.append(aid)
            print(f"[pulled] {aid}  (free {free_gb():.0f}GB)", flush=True)
        else:
            failed.append(aid)
            print(f"[fail] {aid}: could not pull both tags", flush=True)
    print(f"\nPULLED: {' '.join(pulled) or 'none'}")
    print(f"FAILED: {' '.join(failed) or 'none'}")
    print(f"SKIPPED (disk): {' '.join(skipped) or 'none'}")
    sys.exit(0 if pulled else 1)


if __name__ == "__main__":
    main()
