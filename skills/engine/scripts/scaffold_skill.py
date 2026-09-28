#!/usr/bin/env python3
"""Write an adjudicated workflow spec out as an installed Agent Skill.

Everything here is deterministic on purpose. By the time this runs, the readers
have been reconciled and a human has settled the disagreements, so the remaining
job is mechanical: render the spec as a SKILL.md that the host will actually load.
Getting the frontmatter wrong is the common way a generated skill silently fails
to install, so the keys are validated rather than trusted.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

# Agent Skills accepts only these top-level keys; Claude's upload rejects extras.
NAME_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
DEFAULT_ROOT = Path.home() / '.claude' / 'skills'


def yaml_scalar(text: str) -> str:
    """Double-quoted YAML scalar. Safe for colons, quotes, and newlines in descriptions."""
    escaped = str(text).replace('\\', '\\\\').replace('"', '\\"')
    return '"' + re.sub(r'\s+', ' ', escaped).strip() + '"'


def validate(spec: dict) -> list[str]:
    problems = []
    name = str(spec.get('name', '')).strip()
    if not name:
        problems.append('spec.name is required')
    elif not NAME_RE.fullmatch(name):
        problems.append(f'spec.name {name!r} must be lowercase words joined by hyphens')
    if not str(spec.get('description', '')).strip():
        problems.append('spec.description is required — it is what makes the skill trigger')
    if not spec.get('steps'):
        problems.append('spec.steps is empty; there is no workflow to encode')
    return problems


def render_skill(spec: dict) -> str:
    source = spec.get('source') or {}
    version = str(spec.get('version') or '0.1.0')
    lines = ['---',
             f"name: {spec['name']}",
             f"description: {yaml_scalar(spec['description'])}",
             'license: MIT',
             'metadata:',
             f'  version: "{version}"',
             f'  source-video: {yaml_scalar(source.get("url", "unknown"))}',
             f'  derived: {date.today().isoformat()}',
             '---', '',
             f"# {spec['name']}", '']

    if spec.get('goal'):
        lines += [spec['goal'], '']

    lines += ['## Provenance', '',
              f"Derived from a video by two independent readers"
              f"{' (' + ', '.join(source.get('readers', [])) + ')' if source.get('readers') else ''}, "
              'whose disagreements were settled by a human. Steps marked _adjudicated_ were ones the '
              'readers disagreed about, so they carry more risk than the rest.', '']
    if source.get('url'):
        lines += [f"Source: {source['url']}"
                  + (f" — {source['title']}" if source.get('title') else ''), '']

    if spec.get('prerequisites'):
        lines += ['## Prerequisites', '']
        lines += [f'- {item}' for item in spec['prerequisites']]
        lines.append('')

    lines += ['## Steps', '']
    for n, step in enumerate(spec['steps'], 1):
        if isinstance(step, str):
            lines.append(f'{n}. {step}')
            continue
        marks = []
        if step.get('evidence_ts'):
            marks.append(f"video {step['evidence_ts']}")
        if step.get('verified') == 'adjudicated':
            marks.append('adjudicated')
        suffix = f" _({'; '.join(marks)})_" if marks else ''
        lines.append(f"{n}. **{step.get('action', 'step')}**{suffix}")
        if step.get('detail'):
            lines.append(f"   {step['detail']}")
    lines.append('')

    if spec.get('commands'):
        lines += ['## Commands', '', '```bash']
        for item in spec['commands']:
            cmd = item.get('cmd') if isinstance(item, dict) else str(item)
            if isinstance(item, dict) and item.get('evidence_ts'):
                lines.append(f"# video {item['evidence_ts']}")
            lines.append(cmd)
        lines += ['```', '']

    if spec.get('files_touched'):
        lines += ['## Files this touches', '']
        lines += [f'- `{item}`' for item in spec['files_touched']]
        lines.append('')

    if spec.get('gotchas'):
        lines += ['## Gotchas', '']
        lines += [f'- {item}' for item in spec['gotchas']]
        lines.append('')

    if spec.get('open_questions'):
        lines += ['## Unresolved', '',
                  'The video did not settle these. Check before relying on the steps above.', '']
        lines += [f'- {item}' for item in spec['open_questions']]
        lines.append('')

    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path, help='Adjudicated spec JSON')
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT,
                        help=f'Skills directory (default {DEFAULT_ROOT})')
    parser.add_argument('--force', action='store_true', help='Overwrite an existing skill')
    parser.add_argument('--print', dest='print_only', action='store_true',
                        help='Render to stdout without writing')
    args = parser.parse_args()

    try:
        spec = json.loads(args.spec.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise SystemExit(f'[scaffold] no such spec: {args.spec}')
    except json.JSONDecodeError as exc:
        raise SystemExit(f'[scaffold] {args.spec} is not valid JSON: {exc}')

    problems = validate(spec)
    if problems:
        for problem in problems:
            print(f'[scaffold] {problem}', file=sys.stderr)
        return 2

    content = render_skill(spec)
    if args.print_only:
        print(content)
        return 0

    target = args.root / spec['name']
    skill_file = target / 'SKILL.md'
    if skill_file.exists() and not args.force:
        print(f'[scaffold] {skill_file} already exists. Rerun with --force to replace it.',
              file=sys.stderr)
        return 3

    target.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(content, encoding='utf-8')
    print(f'[scaffold] wrote {skill_file}')
    print(f"[scaffold] start a new session, then invoke it with /{spec['name']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
