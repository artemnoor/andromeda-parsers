"""Domain layer reserved for logical-plan value objects.

The first slice keeps its validated value objects in ``contracts`` because
the plan is read-only and has no persistence-owned domain entity.
"""
