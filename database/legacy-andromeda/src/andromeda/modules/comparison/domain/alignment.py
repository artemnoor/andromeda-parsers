from __future__ import annotations

from dataclasses import dataclass

from ....shared.contracts.enums import CompareStatus
from ....shared.contracts.ids import Semester
from .entities import Workload


ComparisonKey = tuple[str, Semester | None]


@dataclass(frozen=True, slots=True)
class AlignedWorkload:
    key: ComparisonKey
    left: Workload | None
    right: Workload | None
    status: CompareStatus


def align_workloads(left: dict[ComparisonKey, Workload], right: dict[ComparisonKey, Workload]) -> tuple[AlignedWorkload, ...]:
    keys = sorted(set(left) | set(right), key=lambda key: (key[0], key[1] is None, key[1] or 0))
    result: list[AlignedWorkload] = []
    for key in keys:
        left_value = left.get(key)
        right_value = right.get(key)
        if left_value is None:
            status = CompareStatus.ONLY_B
        elif right_value is None:
            status = CompareStatus.ONLY_A
        elif left_value == right_value:
            status = CompareStatus.BOTH
        else:
            status = CompareStatus.DIFFERENT
        result.append(AlignedWorkload(key=key, left=left_value, right=right_value, status=status))
    return tuple(result)
