"""Fixed-core overlap zones. Pen zones remain auxiliary, not recursive Chan centres.

The first three lines fix ZD/ZG; subsequent overlaps only extend the envelope.
`done` means exited, not formed: every returned zone has already formed.
"""
from __future__ import annotations

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.types import BI, XD, ZS


def find_zss(bis: list[BI] | list[XD], config: ChanlunConfig | None = None) -> list[ZS]:
    config = config or ChanlunConfig()
    minimum = max(3, config.zs_min_lines)
    result: list[ZS] = []
    cursor = 0
    while cursor + minimum <= len(bis):
        seed = bis[cursor:cursor + 3]
        zg = min(line.high for line in seed)
        zd = max(line.low for line in seed)
        if zg <= zd:
            cursor += 1
            continue
        centre = ZS(lines=list(seed), zg=zg, zd=zd,
                    gg=max(line.high for line in seed), dd=min(line.low for line in seed),
                    start=seed[0].start, end=seed[-1].end, index=len(result))
        next_index = cursor + 3
        while next_index < len(bis):
            line = bis[next_index]
            if line.low >= zg or line.high <= zd:
                centre.done = True
                break
            centre.add_line(line)
            centre.gg = max(centre.gg, line.high)
            centre.dd = min(centre.dd, line.low)
            centre.end = line.end
            next_index += 1
        if centre.line_count >= minimum:
            result.append(centre)
            cursor = next_index
        else:
            cursor += 1
    return result
