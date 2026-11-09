"""Lossless source text plus deterministic, episode-local timed references."""
import re

TS = r'\d+:\d{2}(?:\.\d+)?'
SCENE = re.compile(r'^SCENE\s+(\d+)\s*$', re.M | re.I)
BLOCK = re.compile(r'^\*\*(.+?)\*\*\s*\nStart:\s*\((' + TS + r')\)\s*\|\s*End:\s*\((' + TS + r')\)\s*\n', re.M | re.I)


def seconds(value):
    minute, second = value.split(':')
    if float(second) >= 60:
        raise ValueError(f'Invalid timestamp: {value}')
    return round(int(minute) * 60 + float(second), 4)


def parse_episode(text):
    number = re.search(r'^EPISODE NUMBER:\s*Episode\s+(\d+)', text, re.M | re.I)
    if not number:
        raise ValueError('Missing EPISODE NUMBER: Episode N header')
    n = int(number[1])
    if n < 1:
        raise ValueError('Episode number must be positive')
    def metadata(name):
        m = re.search(r'^' + name + r':\s*(.*)$', text, re.M | re.I)
        return m[1].strip() if m else ''
    scenes, blocks, warnings = [], [], []
    starts = list(SCENE.finditer(text))
    if not starts:
        raise ValueError('No SCENE sections found')
    seen = set()
    for i, scene in enumerate(starts):
        sn = int(scene[1])
        if sn in seen:
            raise ValueError(f'Duplicate scene number {sn}')
        seen.add(sn)
        part = text[scene.end(): starts[i+1].start() if i+1 < len(starts) else len(text)]
        def field(label):
            m = re.search(r'^' + label + r':\s*(.+)$', part, re.M | re.I)
            if not m:
                raise ValueError(f'Scene {sn}: missing {label}')
            return m[1].strip()
        start, end = seconds(field('Scene start')), seconds(field('Scene end'))
        if end <= start:
            raise ValueError(f'Scene {sn}: end must follow start')
        sid = f'ep{n:03d}-scene{sn:03d}'
        scenes.append(dict(id=sid, number=sn, heading=field('Scene heading'), start=start, end=end))
        matches = list(BLOCK.finditer(part))
        for j, match in enumerate(matches):
            label = match[1].rstrip(':').strip()
            body = part[match.end():matches[j+1].start() if j+1 < len(matches) else len(part)]
            body = body.split('--- SCRIPT END ---')[0].strip()
            bs, be = seconds(match[2]), seconds(match[3])
            if be <= bs:
                raise ValueError(f'Scene {sn}: invalid block interval')
            kind = {'CAMERA':'camera', 'ACTION':'action', 'SOUND FX':'sound'}.get(label.upper(), 'dialogue')
            bid = f'ep{n:03d}-block{len(blocks)+1:04d}'
            blocks.append(dict(id=bid, scene_id=sid, kind=kind, label=label,
                               speaker=label.split('(')[0].strip() if kind == 'dialogue' else None,
                               start=bs, end=be, start_timestamp=match[2], end_timestamp=match[3], text=body))
            if bs < start or be > end:
                warnings.append(f'{bid}: extends beyond declared scene boundary')
        if not matches:
            warnings.append(f'{sid}: no timed blocks')
    if not blocks:
        raise ValueError('No timed content blocks found')
    duration = max([s['end'] for s in scenes] + [b['end'] for b in blocks])
    return dict(number=n, logline=metadata('EPISODE LOGLINE'), continuity_notes=metadata('CONTINUITY NOTES'),
                duration=duration, scenes=scenes, blocks=blocks, warnings=warnings)
