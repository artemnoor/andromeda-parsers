"""BMSTU source-shape parsers, hidden behind the adapter boundary.

The adapter is intentionally not imported here: parser modules are imported by
the adapter itself and eager re-exporting would create a circular dependency.
"""

__all__: list[str] = []
