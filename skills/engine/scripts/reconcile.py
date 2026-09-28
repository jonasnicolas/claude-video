#!/usr/bin/env python3
"""Diff two readers' workflow specs and surface only what they disagree about.

The premise of the two-reader design is that both readers are wrong, but wrong in
different places. Where they independently agree, the claim is probably sound and
nobody needs to watch the video to check it. Where they diverge, one of them
misread something — and that is exactly the set a human should spend attention on.

This script does the mechanical comparison only: exact and near-exact text
matching, set differences, and count mismatches. Deciding whether two differently
worded steps mean the same thing is a judgement call, so divergent pairs are
reported rather than silently merged.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

# Above this, two step descriptions are near-identical wording of one action.
SAME_STEP = 0.85
# Below this, there is no credible pairing and the step is unique to one reader.
PAIRABLE = 0.55
# Words too common to mean anything when they differ between two paraphrases.
STOPWORDS = frozenset('''a an the to in on at of and or for with then this that it is are be
from into by as you your its use using run set add open new all if when so we i'''.split())
CONFIDENCE_RANK = {'low': 0, 'medium': 1, 'high': 2}


def normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', str(text or '')).strip().lower()


def load_spec(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise SystemExit(f'[reconcile] no such spec: {path}')
    except json.JSONDecodeError as exc:
        raise SystemExit(f'[reconcile] {path} is not valid JSON: {exc}')
    if not isinstance(data, dict) or 'workflow' not in data:
        raise SystemExit(f'[reconcile] {path} has no "workflow" object; see SKILL.md for the shape.')
    return data


def step_text(step) -> str:
    if isinstance(step, dict):
        return ' '.join(str(step.get(k, '')) for k in ('action', 'detail') if step.get(k))
    return str(step)


def command_text(item) -> str:
    return item.get('cmd', '') if isinstance(item, dict) else str(item)


def content_tokens(text: str) -> set[str]:
    """Meaning-bearing words. Keeps ./-/: so `npm run build` and `pnpm build` stay distinct."""
    return {t for t in re.findall(r'[a-z0-9][\w./:-]*', normalize(text))} - STOPWORDS


def substantive_diff(a, b) -> list[str]:
    """Which words two paraphrases actually disagree on.

    High text similarity is not agreement: 'npm run build' and 'pnpm build' overlap almost
    entirely as characters while describing different commands. That single token is the
    kind of error a second reader exists to catch, so compare words, not ratios.
    """
    return sorted(content_tokens(step_text(a)) ^ content_tokens(step_text(b)))


def confidence_split(a, b) -> bool:
    """A step one reader is sure of and the other barely saw is worth a human's glance."""
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return False
    ranks = [CONFIDENCE_RANK.get(str(s.get('confidence', '')).lower()) for s in (a, b)]
    return None not in ranks and abs(ranks[0] - ranks[1]) >= 2


def compare_sets(a: list, b: list, extract, kind: str) -> tuple[list, list]:
    """Set comparison on normalized text, preserving the readers' original wording."""
    index_a = {normalize(extract(x)): x for x in a if normalize(extract(x))}
    index_b = {normalize(extract(x)): x for x in b if normalize(extract(x))}
    agreed = [index_a[k] for k in index_a if k in index_b]
    conflicts = []
    for key, value in index_a.items():
        if key not in index_b:
            conflicts.append({'kind': f'{kind}_only_in_A', 'reader': 'A', 'value': value})
    for key, value in index_b.items():
        if key not in index_a:
            conflicts.append({'kind': f'{kind}_only_in_B', 'reader': 'B', 'value': value})
    return agreed, conflicts


def align_steps(steps_a: list, steps_b: list) -> tuple[list, list]:
    """Greedy best-similarity pairing; unpaired steps are one reader seeing something alone."""
    texts_a = [normalize(step_text(s)) for s in steps_a]
    texts_b = [normalize(step_text(s)) for s in steps_b]
    scored = []
    for i, ta in enumerate(texts_a):
        for j, tb in enumerate(texts_b):
            if ta and tb:
                scored.append((difflib.SequenceMatcher(None, ta, tb).ratio(), i, j))
    scored.sort(key=lambda row: (-row[0], row[1], row[2]))

    used_a: set[int] = set()
    used_b: set[int] = set()
    agreed, conflicts = [], []
    for ratio, i, j in scored:
        if ratio < PAIRABLE or i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        if ratio < SAME_STEP:
            conflicts.append({'kind': 'step_divergent', 'similarity': round(ratio, 2),
                              'A': steps_a[i], 'B': steps_b[j]})
            continue
        differing = substantive_diff(steps_a[i], steps_b[j])
        if differing:
            conflicts.append({'kind': 'step_detail_divergent', 'similarity': round(ratio, 2),
                              'differing_tokens': differing,
                              'A': steps_a[i], 'B': steps_b[j]})
        elif confidence_split(steps_a[i], steps_b[j]):
            conflicts.append({'kind': 'step_confidence_split', 'similarity': round(ratio, 2),
                              'A': steps_a[i], 'B': steps_b[j]})
        else:
            agreed.append(steps_a[i])
    for i, step in enumerate(steps_a):
        if i not in used_a:
            conflicts.append({'kind': 'step_only_in_A', 'reader': 'A', 'value': step})
    for j, step in enumerate(steps_b):
        if j not in used_b:
            conflicts.append({'kind': 'step_only_in_B', 'reader': 'B', 'value': step})
    return agreed, conflicts


def reconcile(spec_a: dict, spec_b: dict) -> dict:
    wa, wb = spec_a.get('workflow', {}), spec_b.get('workflow', {})
    agreed_steps, step_conflicts = align_steps(wa.get('steps') or [], wb.get('steps') or [])
    agreed_cmds, cmd_conflicts = compare_sets(wa.get('commands') or [], wb.get('commands') or [],
                                              command_text, 'command')
    agreed_files, file_conflicts = compare_sets(wa.get('files_touched') or [],
                                                wb.get('files_touched') or [], str, 'file')
    agreed_prereq, prereq_conflicts = compare_sets(wa.get('prerequisites') or [],
                                                   wb.get('prerequisites') or [], str, 'prerequisite')
    agreed_gotcha, gotcha_conflicts = compare_sets(wa.get('gotchas') or [], wb.get('gotchas') or [],
                                                   str, 'gotcha')

    conflicts = step_conflicts + cmd_conflicts + file_conflicts + prereq_conflicts + gotcha_conflicts
    names = {normalize(wa.get('name')), normalize(wb.get('name'))} - {''}
    if len(names) > 1:
        conflicts.insert(0, {'kind': 'name_mismatch', 'A': wa.get('name'), 'B': wb.get('name')})
    goals = {normalize(wa.get('goal')), normalize(wb.get('goal'))} - {''}
    if len(goals) > 1 and difflib.SequenceMatcher(
            None, normalize(wa.get('goal')), normalize(wb.get('goal'))).ratio() < SAME_STEP:
        conflicts.insert(0, {'kind': 'goal_divergent', 'A': wa.get('goal'), 'B': wb.get('goal')})

    return {
        'readers': {'A': {'engine': spec_a.get('engine'), 'steps': len(wa.get('steps') or [])},
                    'B': {'engine': spec_b.get('engine'), 'steps': len(wb.get('steps') or [])}},
        'independent': spec_a.get('engine') != spec_b.get('engine'),
        'agreed': {'name': wa.get('name') or wb.get('name'), 'goal': wa.get('goal') or wb.get('goal'),
                   'steps': agreed_steps, 'commands': agreed_cmds, 'files_touched': agreed_files,
                   'prerequisites': agreed_prereq, 'gotchas': agreed_gotcha},
        'conflicts': conflicts,
        'summary': {'agreed_steps': len(agreed_steps), 'conflicts': len(conflicts),
                    'agreed_commands': len(agreed_cmds)},
    }


def render(result: dict) -> str:
    readers, summary = result['readers'], result['summary']
    lines = ['# Reader reconciliation', '',
             f"Reader A ({readers['A']['engine']}): {readers['A']['steps']} steps  ·  "
             f"Reader B ({readers['B']['engine']}): {readers['B']['steps']} steps",
             f"Agreed on {summary['agreed_steps']} steps and {summary['agreed_commands']} commands.", '']
    if not result['independent']:
        lines += ['> Both readers used the same engine, so agreement is weaker evidence than it '
                  'looks — they share the same blind spots.', '']
    if not result['conflicts']:
        lines += ['## Nothing to adjudicate', '',
                  'The readers agree everywhere they overlap. Skim the agreed steps anyway: a claim '
                  'both readers missed entirely will not show up as a conflict.']
        return '\n'.join(lines)

    lines += [f"## {len(result['conflicts'])} disagreements — these are the ones worth your time", '']
    for n, conflict in enumerate(result['conflicts'], 1):
        kind = conflict['kind']
        lines.append(f'### {n}. {kind.replace("_", " ")}')
        if 'A' in conflict and 'B' in conflict:
            if conflict.get('differing_tokens'):
                lines.append('_differs on: ' + ', '.join(f'`{t}`' for t in conflict['differing_tokens']) + '_')
            elif 'similarity' in conflict:
                lines.append(f"_similarity {conflict['similarity']}_")
            lines += [f"- **A:** {json.dumps(conflict['A'], ensure_ascii=False)}",
                      f"- **B:** {json.dumps(conflict['B'], ensure_ascii=False)}"]
        else:
            lines.append(f"- **Only reader {conflict.get('reader')}:** "
                         f"{json.dumps(conflict.get('value'), ensure_ascii=False)}")
        lines.append('')
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec_a', type=Path)
    parser.add_argument('spec_b', type=Path)
    parser.add_argument('--out', type=Path, help='Write the reconciliation JSON here')
    parser.add_argument('--markdown', action='store_true', help='Print the human-facing summary')
    args = parser.parse_args()

    result = reconcile(load_spec(args.spec_a), load_spec(args.spec_b))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(render(result) if args.markdown else json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
