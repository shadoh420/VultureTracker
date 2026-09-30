"""Order occurrence mapping; sections are annotations over ordinary IT orders."""
import copy
import json
import re

import yaml

from . import api
from .project import replace_values


def validate_sections(sections, count):
    if sections is None:
        return
    if not isinstance(sections, dict):
        raise ValueError('sections must map names to [first order, exclusive end]')
    occupied = set()
    for name, span in sections.items():
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError('section names must be 1-80 characters')
        if not isinstance(span, list) or len(span) != 2 or any(type(v) is not int for v in span) or not 0 <= span[0] < span[1] <= count:
            raise ValueError(f'section {name}: expected 0 <= first < end <= {count}')
        positions = set(range(*span))
        if occupied & positions:
            raise ValueError('named sections cannot overlap')
        occupied |= positions


def sections_text(text, sections):
    """Keep section value comments; refuse layouts whose comments cannot be retained safely."""
    root = yaml.compose(text, Loader=api._Loader)
    pair = next(((k, v) for k, v in root.value if k.value == 'sections'), None)
    if pair is None:
        return text + ('' if text.endswith('\n') else '\n') + 'sections:\n' + ''.join(
            f'  {json.dumps(n)}: {json.dumps(v)}\n' for n, v in sections.items())
    key, node = pair
    old = api.from_yaml(text).get('sections') or {}
    if isinstance(node, yaml.MappingNode) and set(old) == set(sections):
        return replace_values(text, [(('sections', n, i), number) for n, v in sections.items() for i, number in enumerate(v)])
    if not isinstance(node, yaml.MappingNode) or node.flow_style:
        raw = text[node.start_mark.index:node.end_mark.index]
        if '#' in raw:
            raise ValueError('Expand sections to a block mapping before adding/removing names; its comments must survive')
        prefix = ' ' if node.start_mark.index and text[node.start_mark.index - 1] == ':' else ''
        return text[:node.start_mark.index] + prefix + json.dumps(sections) + text[node.end_mark.index:]
    edits = []
    for k, v in node.value:
        if k.value in sections:
            for item, number in zip(v.value, sections[k.value]):
                edits.append((item.start_mark.index, item.end_mark.index, str(number)))
        else:
            # Preserve comments inside the numeric span too; the trailing comment remains outside this edit.
            comments = re.findall(r'#[^\n]*', text[v.start_mark.index:v.end_mark.index])
            edits.append((k.start_mark.index, v.end_mark.index, '\n  '.join(comments) + ('\n  ' if comments else '')))
    end = node.end_mark.index
    added = ''.join(f'  {json.dumps(n)}: {json.dumps(v)}\n' for n, v in sections.items() if n not in old)
    if added:
        edits.append((end, end, ('\n' if end and text[end-1] != '\n' else '') + added))
    for a, b, value in sorted(edits, reverse=True):
        text = text[:a] + value + text[b:]
    return text


def occurrence_map(before, after):
    """Stable identities for legacy order edits; explicit UI identities disambiguate repeated patterns."""
    remaining = list(enumerate(before))
    out = []
    for name in after:
        item = next(((i, p) for i, p in remaining if p == name), None)
        if item is None:
            out.append(None)
        else:
            remaining.remove(item)
            out.append(item[0])
    return out


def mapped_span(span, mapping):
    ids = [mapping.get(i) for i in range(*span)]
    if not ids or any(i is None for i in ids) or ids != list(range(ids[0], ids[0] + len(ids))):
        return None
    return [ids[0], ids[-1] + 1]


def reorder(state, lines, before, after, origins, meta):
    if len(origins) != len(after) or any(i is not None and (type(i) is not int or not 0 <= i < len(before)) for i in origins):
        raise ValueError('invalid order occurrence mapping')
    mapping = {}
    for new, old in enumerate(origins):
        if old is not None:
            mapping.setdefault(old, new)
    # A deleted jump destination has no safe automatic replacement.
    for name, spec in (api.from_yaml(''.join(lines)).get('patterns') or {}).items():
        data = spec.get('data', '') if isinstance(spec, dict) else str(spec)
        if not api._JUMP.search(data):
            continue
        first, end = state._pattern_block(lines, str(name))
        for i in range(first, end):
            body, sep, comment = lines[i].partition(';')
            lines[i] = api._JUMP.sub(lambda m: _jump(m, mapping), body) + sep + comment
    sections = {}
    for name, span in (state.song.get('sections') or {}).items():
        mapped = mapped_span(span, mapping)
        if mapped is None:
            raise ValueError(f'This would split/remove section {name}; change its boundaries or remove its name first')
        sections[name] = mapped
    if state.song.get('sections') is not None:
        lines[:] = sections_text(''.join(lines), sections).splitlines(keepends=True)
    # Loops use the playable-order index (excluding IT skip/end markers), not the raw order number.
    old_play = [i for i, name in enumerate(before) if name not in ('+++', '---')]
    new_play = [i for i, name in enumerate(after) if name not in ('+++', '---')]
    playable = {j: new_play.index(mapping[i]) for j, i in enumerate(old_play) if i in mapping and mapping[i] in new_play}
    if meta.get('orders'):
        meta['orders'] = mapped_span(meta['orders'], playable)
    if meta.get('loop'):
        lp = meta['loop']
        span = mapped_span([lp['from'][0], lp['to'][0] + 1], playable)
        meta['loop'] = {'from': [span[0], lp['from'][1]], 'to': [span[1]-1, lp['to'][1]]} if span else None
    return mapping


def _jump(match, mapping):
    target = int(match.group(1), 16)
    if target not in mapping:
        raise ValueError(f'B{target:02X} targets a removed order; change that jump before removing the occurrence')
    return f'B{mapping[target]:02X}'
