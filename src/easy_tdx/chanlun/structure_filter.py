"""Filter base-layer outputs without changing segment or recursive definitions."""

from easy_tdx.chanlun.analyser import ChanlunResult


def filter_base_outputs(result: ChanlunResult, minimum: int) -> ChanlunResult:
    if minimum <= 3:
        return result
    result.structural_centres = [
        centre for centre in result.structural_centres if len(centre.member_segments) >= minimum
    ]
    result.structural_signals = [
        event
        for event in result.structural_signals
        if event.evidence.get("centre_segment_count", 0) >= minimum
    ]
    result.mmds = [
        point
        for point in result.mmds
        if point.source != "confirmed_segment_base_v1"
        or point.evidence.get("centre_segment_count", 0) >= minimum
    ]
    result.bcs = [
        point
        for point in result.bcs
        if "centre_segment_count" not in point.evidence
        or point.evidence["centre_segment_count"] >= minimum
    ]
    return result
