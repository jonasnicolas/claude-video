#!/usr/bin/env python3
"""Locate the watch skill, inspect its engine, and assign the two readers.

The readers only produce useful disagreement when their evidence differs, so the
assignment here is the whole ballgame: cross-engine beats dual-gemini because a
frames-and-transcript reader fails in genuinely different places than a model
that watched the whole video. Dual-gemini is the fallback, not the goal.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
LOCAL_BINARIES = ('ffmpeg', 'ffprobe', 'yt-dlp')

# Two lenses on the same video. A tutorial usually shows more than it says and
# says more than it shows, so splitting attention this way surfaces the gaps.
FRAMING_ACTION = ('What the presenter DOES: every command typed, file opened, menu clicked, '
                  'and config edited, in order. Prefer what is on screen over what is narrated.')
FRAMING_INTENT = ('What the presenter MEANS: the goal of each phase, why one approach is chosen '
                  'over another, stated prerequisites, and warnings. Prefer narration over pixels.')


def find_watch_scripts(explicit: str | None = None) -> tuple[Path | None, list[str]]:
    """Resolve the watch skill's scripts directory. Order: explicit, env, sibling, installs."""
    notes = []
    if explicit:
        # An explicit path is a claim, not a hint. Falling back to some other watch
        # install would silently read a different skill than the caller named.
        root = Path(explicit).expanduser()
        scripts = root / 'scripts' if root.name != 'scripts' else root
        if (scripts / 'watch.py').is_file():
            return scripts, notes
        return None, [f'--watch-dir {root} has no scripts/watch.py']

    candidates = []
    env = os.environ.get('WATCH_SKILL_DIR', '').strip()
    if env:
        candidates.append(Path(env).expanduser())
    # The normal case: engine/ and watch/ are siblings in one plugin.
    candidates.append(SKILL_DIR.parent / 'watch')
    for root in (Path.home() / '.claude' / 'skills', Path.home() / '.config' / 'agents' / 'skills'):
        candidates.append(root / 'watch')

    for candidate in candidates:
        scripts = candidate / 'scripts' if candidate.name != 'scripts' else candidate
        if (scripts / 'watch.py').is_file():
            return scripts, notes
        notes.append(f'no watch.py under {scripts}')
    return None, notes


def watch_status(scripts: Path, python: str) -> tuple[dict, str | None]:
    """Ask watch's own setup.py what it can do. Never reimplement its config logic."""
    try:
        proc = subprocess.run([python, str(scripts / 'setup.py'), '--json'],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return {}, f'could not run watch setup.py: {exc}'
    if proc.returncode != 0 and not proc.stdout.strip():
        detail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f'exit {proc.returncode}'
        return {}, f'watch setup.py failed: {detail}'
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError:
        return {}, 'watch setup.py did not return JSON'


def plan_readers(gemini: bool, local: bool) -> tuple[str, list[dict], list[str]]:
    warnings = []
    if gemini and local:
        mode = 'cross-engine'
        readers = [
            {'id': 'A', 'engine': 'gemini', 'framing': FRAMING_INTENT,
             'watch_args': ['--engine', 'gemini']},
            {'id': 'B', 'engine': 'local', 'framing': FRAMING_ACTION,
             'watch_args': ['--engine', 'local', '--detail', 'balanced']},
        ]
    elif gemini:
        mode = 'dual-gemini'
        readers = [
            {'id': 'A', 'engine': 'gemini', 'framing': FRAMING_INTENT,
             'watch_args': ['--engine', 'gemini']},
            {'id': 'B', 'engine': 'gemini', 'framing': FRAMING_ACTION,
             'watch_args': ['--engine', 'gemini']},
        ]
        warnings.append('Both readers use Gemini, so they share its blind spots. Agreement here is '
                        'weaker evidence than cross-engine agreement. Install ffmpeg and yt-dlp '
                        '(bash setup-watch.sh --local) to get an independent second reader.')
    elif local:
        mode = 'dual-local'
        readers = [
            {'id': 'A', 'engine': 'local', 'framing': FRAMING_INTENT,
             'watch_args': ['--engine', 'local', '--detail', 'balanced']},
            {'id': 'B', 'engine': 'local', 'framing': FRAMING_ACTION,
             'watch_args': ['--engine', 'local', '--detail', 'token-burner']},
        ]
        warnings.append('No Gemini key, so both readers read frames and transcript. They differ '
                        'only in sampling density and framing.')
    else:
        mode = 'none'
        readers = []
        warnings.append('Neither engine is usable: no Gemini key and no ffmpeg/yt-dlp.')
    return mode, readers, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch-dir', help='Explicit path to the watch skill (or its scripts/)')
    parser.add_argument('--json', action='store_true', help='Machine-readable output')
    args = parser.parse_args()

    python = sys.executable or 'python3'
    scripts, notes = find_watch_scripts(args.watch_dir)
    report: dict = {'watch_found': scripts is not None,
                    'watch_scripts_dir': str(scripts) if scripts else None,
                    'python': python, 'search_notes': notes}

    if scripts is None:
        report.update(ready=False, mode='none', readers=[], warnings=[
            'The watch skill was not found. /engine drives /watch and cannot run without it. '
            'Install it (/plugin install watch@claude-video) or pass --watch-dir.'])
        print(json.dumps(report, indent=2) if args.json else report['warnings'][0], file=sys.stderr)
        return 2

    status, error = watch_status(scripts, python)
    local = all(shutil.which(binary) for binary in LOCAL_BINARIES)
    gemini = bool(status.get('gemini_key_present'))
    mode, readers, warnings = plan_readers(gemini, local)
    if error:
        warnings.append(error)

    report.update(ready=bool(readers), mode=mode, readers=readers, warnings=warnings,
                  gemini_available=gemini, local_available=local,
                  watch_engine=status.get('engine'),
                  missing_binaries=[b for b in LOCAL_BINARIES if not shutil.which(b)])

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f'watch: {scripts}')
        print(f'mode: {mode} (gemini={gemini}, local={local})')
        for reader in readers:
            print(f'  reader {reader["id"]}: engine={reader["engine"]}')
        for warning in warnings:
            print(f'  ! {warning}')
    return 0 if readers else 2


if __name__ == '__main__':
    raise SystemExit(main())
