"""Validate ARVO pairs and lay out real-report folders (C1); text generation is C2.

Run first on two ids with ``--limit 2`` (a dry run). For every id the builder does a
single differential check inside networkless Sandbox containers: the literal ``/out``
fuzz target must crash under a sanitizer on ``-vul`` and run clean on ``-fix`` using the
*same* PoC bytes. Nothing here calls the ARVO ``arvo`` replay command, and no part of
the ground truth (``meta.json``, ``ground_truth.txt``, sanitizer logs, the label) is
ever passed to a model. ``--validate-only`` (the C1 default) makes zero model calls.

Each validated id yields two report folders, both self-contained:

    datasets/real/arvo-<id>-with_poc/     attachments/poc.bin present   (label: real)
    datasets/real/arvo-<id>-text_only/    no attachments                (label: real)

C2 fills in ``report.md`` from the crash facts; C1 only proves the pair and copies bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from repro import sanitizer
from repro.prompts import load_prompt, wrap_untrusted
from repro.sandbox import Sandbox
from repro.schemas import Target
from repro.trace import Tracer

MODES = ("with_poc", "text_only")
# Giant source trees whose ARVO images build/run far too slowly for the eval set. The ARVO-Meta
# "project" label is unreliable (some ids labelled as a small lib crash inside a bundled llvm),
# so this is checked against the *validated* crash's project, not the shortlist label.
GIANT_PROJECTS = frozenset({
    "llvm-project", "llvm", "skia", "chromium", "chrome", "v8", "pdfium", "firefox",
    "mozilla", "gecko-dev", "webkit", "tensorflow", "node", "nodejs", "android", "swift",
})
# Eval-only artifacts written beside each report. io.load_report never reads these
# (it only loads attachments/*), so they stay host-side ground truth, never model input.
GROUND_TRUTH_FILES = ("arvo_script.txt", "ground_truth.txt", "fixed_output.txt", "meta.json")


@dataclass
class Bundle:
    """Everything one validated ARVO pair needs to materialise its report folders."""
    result: dict
    poc: bytes
    arvo_script: str
    ground_truth: str
    fixed_output: str = field(repr=False, default="")


def _free_gb(path: str = '/') -> float:
    return shutil.disk_usage(path).free / 1e9


def _pull_pair(aid: str) -> None:
    """Pull both ARVO tags; raise RuntimeError if either fails (id then skipped)."""
    for tag in (f'n132/arvo:{aid}-vul', f'n132/arvo:{aid}-fix'):
        if subprocess.run(['docker', 'pull', '-q', tag], capture_output=True, timeout=3600).returncode:
            raise RuntimeError(f'docker pull failed for {tag}')


def _remove_images(aid: str, tags: tuple[str, ...]) -> None:
    for tag in tags:
        subprocess.run(['docker', 'rmi', '-f', f'n132/arvo:{aid}-{tag}'], capture_output=True, timeout=120)
    subprocess.run(['docker', 'image', 'prune', '-f'], capture_output=True, timeout=600)


def _free_fix_image(aid: str) -> None:
    """Reclaim disk: drop the -fix image (kept only where the patch demo needs it) and prune layers."""
    _remove_images(aid, ('fix',))


def reproducer(script: str) -> tuple[list[str], str]:
    """Read a literal fuzzer invocation from the arvo wrapper; never execute the wrapper."""
    commands = set()
    for line in script.splitlines():
        if not line.strip().startswith('/out/'):
            continue
        args = shlex.split(line, comments=True)
        # Reject shell expansions, redirections and control operators, even when quoted.
        if any(re.search(r"[$`;&|<>\n]", arg) for arg in args):
            raise ValueError("nonliteral fuzzer command in wrapper")
        inputs = [arg for arg in args[1:] if arg.startswith('/tmp/')]
        if len(inputs) == 1:
            commands.add((tuple(args), inputs[0]))
    if len(commands) != 1:
        raise ValueError("expected exactly one literal /out/ fuzzer command and /tmp/ input")
    args, poc = commands.pop()
    return list(args), poc


def read_poc_bytes(sb: Sandbox, source: str) -> bytes:
    """Copy PoC bytes out of the container, reject symlinks/empty, clean up the temp file."""
    assert sb.cid
    with tempfile.TemporaryDirectory(prefix='c1-poc-') as tmp:
        copied = Path(tmp) / 'poc.bin'
        subprocess.run(['docker', 'cp', f'{sb.cid}:{source}', str(copied)],
                       check=True, capture_output=True, timeout=60)
        if copied.is_symlink() or not copied.is_file():
            raise ValueError('PoC must be a regular file')
        data = copied.read_bytes()
    if not data:
        raise ValueError('empty PoC')
    return data


def validate(aid: str, timeout: int, tracer: Tracer) -> Bundle:
    """Keep only a real sanitizer crash on -vul followed by a clean -fix run on identical bytes."""
    if not re.fullmatch(r'[0-9]+', aid):
        raise ValueError('ARVO ids must contain digits only')
    vul, fix = f'n132/arvo:{aid}-vul', f'n132/arvo:{aid}-fix'
    # This offline dataset builder intentionally retains the image's ground-truth PoC so it
    # can copy the bytes out. The production Sandbox default scrub (/tmp/poc) is unchanged.
    target = Target(project='unknown', image=vul, fixed_image=fix, src_dir='/', scrub_paths=[])
    with Sandbox(target) as sb:
        wrapper = sb.exec('cat /bin/arvo', timeout=15, workdir='/')
        if wrapper.exit_code:
            raise ValueError('cannot read /bin/arvo')
        args, poc_path = reproducer(wrapper.stdout)
        data = read_poc_bytes(sb, poc_path)
        sb.write_file('/work/c1-poc', data)
        command = shlex.join(['/work/c1-poc' if arg == poc_path else arg for arg in args])
        vulnerable = sb.exec(command, timeout=timeout, workdir='/tmp')
    report = sanitizer.parse(vulnerable.stdout + vulnerable.stderr)
    if vulnerable.timed_out or vulnerable.exit_code == 0 or not report:
        raise ValueError('vulnerable run did not produce a sanitizer crash')
    frames = [f for f in report.top_project_frames() if f.file and f.file.startswith('/src/')]
    if not frames:
        raise ValueError('no symbolized project frame')
    top = frames[0]
    project = top.file.split('/')[2]
    fixed_sb = Sandbox(target)
    try:
        fixed_sb.start(image=fix)
        fixed_sb.write_file('/work/c1-poc', data)
        fixed = fixed_sb.exec(command, timeout=timeout, workdir='/tmp')
    finally:
        fixed_sb.stop()
    result = {'id': aid, 'project': project, 'image': vul, 'fixed_image': fix,
              'command': command, 'poc_source': poc_path, 'poc_sha256': hashlib.sha256(data).hexdigest(),
              'poc_bytes': len(data), 'function': top.function, 'file': top.file,
              'bug_type': report.error_type, 'fuzz_target': args[0],
              'vulnerable': vulnerable.model_dump(), 'fixed': fixed.model_dump(),
              'checked_at': datetime.now(timezone.utc).isoformat()}
    tracer.log('validate', 'differential_check', result)
    if fixed.timed_out or fixed.exit_code != 0 or sanitizer.parse(fixed.stdout + fixed.stderr):
        raise ValueError(f'fixed run failed or still crashes (exit {fixed.exit_code})')
    return Bundle(result=result, poc=data, arvo_script=wrapper.stdout,
                  ground_truth=vulnerable.stdout + vulnerable.stderr,
                  fixed_output=fixed.stdout + fixed.stderr)


def materialize(root: Path, bundle: Bundle, modes: tuple[str, ...]) -> list[str]:
    """Write one self-contained report folder per mode; only with_poc carries the PoC."""
    aid = bundle.result['id']
    written = []
    for mode in modes:
        directory = root / f'arvo-{aid}-{mode}'
        (directory / 'attachments').mkdir(parents=True, exist_ok=True)
        (directory / 'arvo_script.txt').write_text(bundle.arvo_script)
        (directory / 'ground_truth.txt').write_text(bundle.ground_truth)
        (directory / 'fixed_output.txt').write_text(bundle.fixed_output)
        meta = dict(bundle.result, mode=mode, directory=directory.name)
        (directory / 'meta.json').write_text(json.dumps(meta, indent=2) + '\n')
        poc = directory / 'attachments' / 'poc.bin'
        if mode == 'with_poc':
            poc.write_bytes(bundle.poc)
        else:  # text_only ships no PoC; drop any PoC left from an earlier with_poc build
            poc.unlink(missing_ok=True)
        written.append(directory.name)
    return written


def write_index(root: Path, rows: list[dict]) -> None:
    lines = ['# Validated ARVO shortlist', '',
             'Each row has a nonzero sanitizer crash on `-vul` and exit 0 with no sanitizer on `-fix`.',
             'Both runs use the same copied PoC bytes inside networkless Sandbox containers. No ARVO replay or model calls.',
             'Every id ships two folders: `-with_poc` (PoC attached) and `-text_only`. '
             'Logs, wrapper, PoC and `meta.json` are eval-only (never shown to a model).', '',
             '| ID | Project | Sanitizer error | Vulnerable exit | Fixed exit | Evidence |',
             '|---|---|---|---|---|---|']
    for row in rows:
        folder = f'arvo-{row["id"]}-with_poc'
        lines.append(f'| {row["id"]} | {row["project"]} | {row["bug_type"]} | '
                     f'{row["vulnerable"]["exit_code"]} | {row["fixed"]["exit_code"]} | '
                     f'[{folder}]({folder}/meta.json) |')
    lines.append('')
    lines.append(f'**{len(rows)} validated id(s).**')
    (root / 'IDS.md').write_text('\n'.join(lines) + '\n')


def load_existing(root: Path) -> list[dict]:
    """Already-validated rows, read from each arvo-*-with_poc/meta.json (deduped, ordered by id)."""
    rows, seen = [], set()
    for meta in sorted(root.glob('arvo-*-with_poc/meta.json'), key=lambda p: p.parent.name):
        try:
            row = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        aid = row.get('id')
        if aid and aid not in seen:
            seen.add(aid)
            rows.append(row)
    return rows


def write_report(row: dict, directory: Path, mode: str, src_dir: str | None, llm) -> None:
    """C2 only: generate report.md from an allowlist of crash facts (no label, logs or meta)."""
    user = {key: row[key] for key in ('project', 'function', 'file', 'bug_type', 'fuzz_target')}
    user['mode'] = mode
    response = llm.chat([{'role': 'system', 'content': load_prompt('report_from_arvo')},
                         {'role': 'user', 'content': wrap_untrusted('crash facts', json.dumps(user))}],
                        response_format={'type': 'json_object'}, temperature=0.4, stage='note')
    data = json.loads(response.choices[0].message.content)
    fm = {'id': directory.name, 'title': data['title'], 'source': 'synthetic', 'label': 'real',
          'target': {'project': row['project'], 'image': row['image'], 'fixed_image': row['fixed_image'],
                     'src_dir': src_dir or f'/src/{row["project"]}', 'build_cmd': 'arvo compile',
                     'repro_cmd': None, 'test_cmd': None}}
    (directory / 'report.md').write_text('---\n' + yaml.safe_dump(fm, sort_keys=False) + '---\n' + data['body'])


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ids', nargs='+', required=True)
    parser.add_argument('--modes', nargs='+', choices=MODES, default=list(MODES),
                        help='report folders to build per id (default: both)')
    parser.add_argument('--out', default='datasets/real')
    parser.add_argument('--src-dir', default=None)
    parser.add_argument('--validate-only', action='store_true',
                        help='C1: prove pairs and lay out folders, zero model calls (report.md is C2)')
    parser.add_argument('--limit', type=int, help='use 2 for the first dry run')
    parser.add_argument('--timeout', type=int, default=60)
    parser.add_argument('--pull', action='store_true',
                        help='docker pull each -vul/-fix pair before validating (disk-guarded)')
    parser.add_argument('--min-free-gb', type=float, default=25.0,
                        help='with --pull: skip an id if free disk would drop below this')
    parser.add_argument('--free-fix', action='store_true',
                        help='after a pair validates, delete its -fix image (except --keep-fix) and prune')
    parser.add_argument('--keep-fix', nargs='*', default=['42487096'],
                        help='ids whose -fix image is retained (patch demo); default: 42487096')
    parser.add_argument('--skip-validated', action='store_true',
                        help='skip ids already validated under --out (and count them toward --stop-after)')
    parser.add_argument('--stop-after', type=int,
                        help='stop once this many ids are validated in total (existing + this run)')
    args = parser.parse_args()
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    modes = tuple(dict.fromkeys(args.modes))
    keep_fix = set(args.keep_fix)
    tracer = Tracer('c1-arvo-validation')
    llm = None
    if not args.validate_only:
        from repro.llm import LLM
        llm = LLM.cheap(tracer=tracer)
    rows = load_existing(root) if args.skip_validated else []
    done = {r['id'] for r in rows}
    failed = []
    write_index(root, rows)
    print(f'[start] {len(rows)} already validated; target {args.stop_after or "all"}; '
          f'free {_free_gb():.0f}GB', flush=True)
    for aid in list(dict.fromkeys(args.ids))[:args.limit]:
        if args.stop_after and len(rows) >= args.stop_after:
            print(f'[done] reached {len(rows)} validated ids; stopping', flush=True)
            break
        if aid in done:
            print(f'[have] {aid}: already validated', flush=True)
            continue
        t0 = time.time()
        pull_s = 0.0
        try:
            if args.pull:
                if _free_gb() < args.min_free_gb:
                    raise RuntimeError(f'free disk {_free_gb():.0f}GB below floor {args.min_free_gb:.0f}GB')
                p0 = time.time()
                _pull_pair(aid)
                pull_s = time.time() - p0
            bundle = validate(aid, args.timeout, tracer)
            if bundle.result['project'] in GIANT_PROJECTS:
                tracer.log('error', 'excluded_giant', {'id': aid, 'project': bundle.result['project']})
                _remove_images(aid, ('vul', 'fix'))
                print(f'[excluded] {aid} {bundle.result["project"]} giant source tree; '
                      f'not counted; free {_free_gb():.0f}GB', flush=True)
                continue
            folders = materialize(root, bundle, modes)
            if llm:
                for mode, folder in zip(modes, folders, strict=True):
                    write_report(bundle.result, root / folder, mode, args.src_dir, llm)
            rows.append(bundle.result)
            done.add(aid)
            if args.free_fix and aid not in keep_fix:
                _free_fix_image(aid)
            print(f'[validated] {aid} {bundle.result["project"]} {bundle.result["bug_type"]} '
                  f'{time.time() - t0:.0f}s (pull {pull_s:.0f}s) total={len(rows)} free={_free_gb():.0f}GB',
                  flush=True)
        except (ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            failed.append({'id': aid, 'reason': str(exc)})
            tracer.log('error', 'validation_rejected', failed[-1])
            print(f'[failed] {aid} {time.time() - t0:.0f}s reason="{exc}"', flush=True)
        write_index(root, rows)
        (root / 'rejected.json').write_text(json.dumps(failed, indent=2) + '\n')  # kept current after each id
    print(f'[summary] {len(rows)} validated; {len(failed)} failed; '
          f'model calls: {llm.usage.calls if llm else 0}', flush=True)


if __name__ == '__main__':
    main()
