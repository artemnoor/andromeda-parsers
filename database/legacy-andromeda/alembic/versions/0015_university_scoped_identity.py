"""Namespace university-owned canonical identities for multi-university data."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0015_university_scoped_identity"
down_revision = "0014_decision_analytics"
branch_labels = None
depends_on = None


IDENTITY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("directions", "id"),
    ("educational_programs", "id"),
    ("curricula", "id"),
    ("curriculum_items", "id"),
    ("admission_offerings", "id"),
    ("decision_contexts", "state_json"),
    ("decision_analytics_events", "payload_json"),
    ("user_profiles", "profile_json"),
    ("proftest_sessions", "session_json"),
)


def upgrade() -> None:
    bind = op.get_bind()
    old_directions = _rows(bind, "SELECT id FROM directions WHERE id LIKE 'direction:%' AND id NOT LIKE 'direction:%:%'")
    old_programs = _rows(bind, "SELECT id FROM educational_programs WHERE id LIKE 'program:%' AND id NOT LIKE 'program:%:%'")
    old_curricula = _rows(bind, "SELECT id FROM curricula WHERE id LIKE 'curriculum:%' AND id NOT LIKE 'curriculum:%:%'")

    _disable_referential_checks(bind)
    try:
        for old_id in old_directions:
            _replace_everywhere(bind, old_id, f"direction:bmstu:{old_id.removeprefix('direction:')}")
        for old_id in old_programs:
            _replace_everywhere(bind, old_id, f"program:bmstu:{old_id.removeprefix('program:')}")
        for old_id in old_curricula:
            _replace_everywhere(bind, old_id, f"curriculum:bmstu:{old_id.removeprefix('curriculum:')}")
        _rebuild_identity_constraints(bind, legacy=False)
    finally:
        _enable_referential_checks(bind)


def downgrade() -> None:
    bind = op.get_bind()
    non_bmstu = bind.execute(
        sa.text(
            "SELECT count(*) FROM directions "
            "WHERE id LIKE 'direction:%:%' AND id NOT LIKE 'direction:bmstu:%'"
        )
    ).scalar_one()
    if non_bmstu:
        raise RuntimeError("cannot downgrade university-scoped identity while non-BMSTU data exists")

    _disable_referential_checks(bind)
    try:
        for table, column in IDENTITY_COLUMNS:
            if _has_table(bind, table):
                _replace_column(bind, table, column, "direction:bmstu:", "direction:")
                _replace_column(bind, table, column, "program:bmstu:", "program:")
                _replace_column(bind, table, column, "curriculum:bmstu:", "curriculum:")
                _replace_column(bind, table, column, "curriculum-item:program:bmstu:", "curriculum-item:program:")
        _replace_column(bind, "directions", "id", "direction:bmstu:", "direction:")
        _replace_column(bind, "educational_programs", "id", "program:bmstu:", "program:")
        _replace_column(bind, "educational_programs", "direction_id", "direction:bmstu:", "direction:")
        _replace_column(bind, "curricula", "id", "curriculum:bmstu:", "curriculum:")
        _replace_column(bind, "curricula", "program_id", "program:bmstu:", "program:")
        _replace_column(bind, "curriculum_items", "id", "curriculum-item:program:bmstu:", "curriculum-item:program:")
        _replace_column(bind, "curriculum_items", "curriculum_id", "curriculum:bmstu:", "curriculum:")
        _replace_column(bind, "admission_offerings", "program_id", "program:bmstu:", "program:")
        _rebuild_identity_constraints(bind, legacy=True)
    finally:
        _enable_referential_checks(bind)


def _rows(bind: sa.Connection, query: str) -> tuple[str, ...]:
    return tuple(str(row[0]) for row in bind.execute(sa.text(query)).all())


def _replace_everywhere(bind: sa.Connection, old: str, new: str) -> None:
    for table, column in _existing_identity_columns(bind):
        _replace_column(bind, table, column, old, new)
    # Foreign-key columns and link tables are explicit because they may not be
    # JSON columns and are not part of the public identity payload list above.
    for table, column in (
        ("directions", "university_id"),
        ("educational_programs", "direction_id"),
        ("curricula", "program_id"),
        ("curriculum_items", "curriculum_id"),
        ("admission_offerings", "program_id"),
        ("admission_exam_requirements", "offering_id"),
        ("admission_quotas", "offering_id"),
        ("admission_passing_scores", "offering_id"),
        ("admission_tuition", "offering_id"),
        ("curriculum_item_assessments", "curriculum_item_id"),
        ("event_program_links", "program_id"),
        ("venue_program_links", "program_id"),
    ):
        if _has_column(bind, table, column):
            _replace_column(bind, table, column, old, new)


def _existing_identity_columns(bind: sa.Connection) -> tuple[tuple[str, str], ...]:
    return tuple((table, column) for table, column in IDENTITY_COLUMNS if _has_column(bind, table, column))


def _replace_column(bind: sa.Connection, table: str, column: str, old: str, new: str) -> None:
    if not _has_column(bind, table, column):
        return
    bind.execute(
        sa.text(f"UPDATE {table} SET {column} = replace({column}, :old, :new) WHERE instr({column}, :old) > 0"),
        {"old": old, "new": new},
    )


def _has_table(bind: sa.Connection, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _has_column(bind: sa.Connection, table: str, column: str) -> bool:
    return _has_table(bind, table) and any(item["name"] == column for item in sa.inspect(bind).get_columns(table))


def _disable_referential_checks(bind: sa.Connection) -> None:
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
        bind.exec_driver_sql("PRAGMA ignore_check_constraints=ON")
    elif bind.dialect.name == "postgresql":
        for table in ("curriculum_item_assessments", "curriculum_items", "curricula", "admission_offerings", "educational_programs", "directions", "event_program_links", "venue_program_links", "decision_contexts", "decision_analytics_events", "user_profiles", "proftest_sessions"):
            if _has_table(bind, table):
                bind.exec_driver_sql(f"ALTER TABLE {table} DISABLE TRIGGER ALL")


def _enable_referential_checks(bind: sa.Connection) -> None:
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("PRAGMA ignore_check_constraints=OFF")
        bind.exec_driver_sql("PRAGMA foreign_keys=ON")
    elif bind.dialect.name == "postgresql":
        for table in ("curriculum_item_assessments", "curriculum_items", "curricula", "admission_offerings", "educational_programs", "directions", "event_program_links", "venue_program_links", "decision_contexts", "decision_analytics_events", "user_profiles", "proftest_sessions"):
            if _has_table(bind, table):
                bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER ALL")


def _rebuild_identity_constraints(bind: sa.Connection, *, legacy: bool) -> None:
    if bind.dialect.name == "sqlite":
        direction_check = "id = 'direction:' || code" if legacy else "id LIKE 'direction:%:%'"
        program_check = "id = 'program:' || code" if legacy else "id LIKE 'program:%:%'"
        direction_constraint = "ck_direction_id_matches_university" if legacy else "ck_direction_id_matches_code"
        program_constraint = "ck_program_id_matches_university" if legacy else "ck_program_id_matches_code"
        with op.batch_alter_table("directions", recreate="always") as batch:
            batch.drop_constraint(direction_constraint)
            batch.create_check_constraint("ck_direction_id_matches_code" if legacy else "ck_direction_id_matches_university", direction_check)
        with op.batch_alter_table("educational_programs", recreate="always") as batch:
            batch.drop_constraint(program_constraint)
            batch.create_check_constraint("ck_program_id_matches_code" if legacy else "ck_program_id_matches_university", program_check)
        return

    op.drop_constraint("ck_direction_id_matches_university" if legacy else "ck_direction_id_matches_code", "directions", type_="check")
    op.drop_constraint("ck_program_id_matches_university" if legacy else "ck_program_id_matches_code", "educational_programs", type_="check")
    op.create_check_constraint(
        "ck_direction_id_matches_code" if legacy else "ck_direction_id_matches_university",
        "directions",
        "id = 'direction:' || code" if legacy else "id LIKE 'direction:%:%'",
    )
    op.create_check_constraint(
        "ck_program_id_matches_code" if legacy else "ck_program_id_matches_university",
        "educational_programs",
        "id = 'program:' || code" if legacy else "id LIKE 'program:%:%'",
    )
