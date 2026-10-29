"""
sql/schema.sql is the from-scratch reference and must stay in step with sql/migrations/ BY HAND
(sql/migrations/README.md). It had drifted (found 2026-10-29: provider-id columns, void_reason, three
tables, two views and two indexes existed in production but not in schema.sql), so a database rebuilt
from the repo did not match production. This guard fails when a migration creates a table, view, column,
index, function or trigger that neither schema.sql nor features.sql defines.

Static text check only (no database). The full proof is a rebuild-and-diff against production, which is
how the drift was found and fixed; see the commit message.
"""
import glob
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _strip(sql: str) -> str:
    return re.sub(r"/\*.*?\*/", "", re.sub(r"--[^\n]*", "", sql), flags=re.S)


# Comments are stripped: a name mentioned only in prose must not count as defined.
REFERENCE = _strip("\n".join(open(os.path.join(ROOT, "sql", f)).read() for f in ("schema.sql", "features.sql")))

# Objects a migration creates that a later migration drops, or that live outside the reference on purpose.
EXEMPT: dict[str, str] = {}


def _created(sql: str):
    sql = _strip(sql)
    name = r"(?:futbol\.)?([A-Za-z_][A-Za-z0-9_]*)"
    for m in re.finditer(rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{name}", sql, re.I):
        yield "table", m.group(1)
    for m in re.finditer(rf"CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW\s+{name}", sql, re.I):
        yield "view", m.group(1)
    for m in re.finditer(rf"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?{name}", sql, re.I):
        yield "index", m.group(1)
    for m in re.finditer(rf"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+{name}", sql, re.I):
        yield "function", m.group(1)
    for m in re.finditer(rf"CREATE\s+TRIGGER\s+{name}", sql, re.I):
        yield "trigger", m.group(1)
    for m in re.finditer(rf"ALTER\s+TABLE\s+(?:ONLY\s+)?{name}\s+(.*?);", sql, re.I | re.S):
        for c in re.finditer(r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)", m.group(2), re.I):
            yield "column", f"{m.group(1)}.{c.group(1)}"


def _dropped(sql: str) -> set[str]:
    sql = _strip(sql)
    out = set()
    for m in re.finditer(r"DROP\s+(?:TABLE|VIEW|INDEX|FUNCTION|TRIGGER|MATERIALIZED\s+VIEW)\s+(?:IF\s+EXISTS\s+)?"
                         r"(?:futbol\.)?([A-Za-z_][A-Za-z0-9_]*)", sql, re.I):
        out.add(m.group(1))
    for m in re.finditer(r"DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)", sql, re.I):
        out.add(m.group(1))
    return out


def _defined(kind: str, ident: str) -> bool:
    if kind == "column":
        table, col = ident.split(".")
        block = re.search(rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:futbol\.)?{table}\s*\((.*?)\n\)\s*;",
                          REFERENCE, re.I | re.S)
        if block and re.search(rf"\b{col}\b", block.group(1)):
            return True
        return bool(re.search(rf"ALTER\s+TABLE\s+(?:ONLY\s+)?(?:futbol\.)?{table}\b[^;]*\b{col}\b", REFERENCE, re.I))
    return bool(re.search(rf"\b{ident}\b", REFERENCE))


def test_every_object_a_migration_creates_is_in_the_from_scratch_reference():
    files = sorted(glob.glob(os.path.join(ROOT, "sql", "migrations", "*.sql")))
    texts = {os.path.basename(f): open(f).read() for f in files}
    dropped_later: dict[str, set[str]] = {}
    names = sorted(texts)
    for i, n in enumerate(names):
        later: set[str] = set()
        for n2 in names[i + 1:]:
            later |= _dropped(texts[n2])
        dropped_later[n] = later
    missing = []
    for n in names:
        for kind, ident in _created(texts[n]):
            key = ident.split(".")[-1]
            if ident in EXEMPT or key in dropped_later[n] or _defined(kind, ident):
                continue
            missing.append(f"{n}: {kind} {ident}")
    detail = "\n  ".join(missing)
    assert not missing, f"created by a migration but absent from sql/schema.sql and sql/features.sql:\n  {detail}"
