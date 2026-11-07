"""Static checks on model-written SQL before it reaches the database.

This is the second layer of protection. The first (and the real guarantee) is the
`mimelee_agent` database role: read-only, SELECT on the `agent` views only, 5s
timeout. This layer exists so bad queries fail fast with an error message the model
can learn from, and so nothing odd reaches Postgres even if the role were
misconfigured.
"""
import sqlglot
from sqlglot import exp

ALLOWED_VIEWS = frozenset({
    'players', 'tournaments', 'sets', 'player_sets', 'placements', 'pr_seasons', 'pr_rankings',
})
MAX_ROWS = 200

# Functions a SELECT could use to touch server state, files, other databases or sleep.
_BLOCKED_FUNCTION_PREFIXES = ('pg_', 'lo_', 'dblink', 'set_config', 'current_setting',
                              'txid_', 'query_to_xml', 'table_to_xml', 'database_to_xml',
                              'cursor_to_xml', 'xpath', 'nextval', 'setval', 'currval',
                              'inet_', 'version')

# Every node type that changes data, schema, session state or locks rows.
_BLOCKED_NODES = tuple(t for t in (
    getattr(exp, n, None) for n in (
        'Insert', 'Update', 'Delete', 'Merge', 'Create', 'Drop', 'Alter', 'AlterTable',
        'TruncateTable', 'Command', 'Set', 'Use', 'Grant', 'Revoke', 'Copy', 'Transaction',
        'Commit', 'Rollback', 'Lock', 'LoadData', 'Into', 'Pragma', 'Analyze', 'Describe',
    )) if t is not None)


class SQLRejected(ValueError):
    """The query is not allowed. The message is written for the model to read and fix."""


def check_sql(sql):
    """Return a safe, row-limited version of `sql` or raise SQLRejected."""
    if not isinstance(sql, str) or not sql.strip():
        raise SQLRejected('Empty query.')
    if len(sql) > 4000:
        raise SQLRejected('Query is too long; simplify it.')

    try:
        statements = [s for s in sqlglot.parse(sql, read='postgres') if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise SQLRejected(f'Could not parse the SQL: {str(exc).splitlines()[0]}') from exc
    if len(statements) != 1:
        raise SQLRejected('Send exactly one SELECT statement (no semicolon-separated statements).')
    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        raise SQLRejected('Only SELECT queries (optionally with WITH ...) are allowed.')

    for node in tree.walk():
        if isinstance(node, _BLOCKED_NODES):
            raise SQLRejected(f'{node.key.upper()} is not allowed; this is a read-only SELECT tool.')
        if isinstance(node, exp.Lock):
            raise SQLRejected('Locking clauses (FOR UPDATE/SHARE) are not allowed.')

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        schema = (table.db or '').lower()
        if not name:
            raise SQLRejected('Table functions are not allowed; select from the agent views.')
        if name in cte_names and not schema:
            continue
        if schema not in ('', 'agent') or name not in ALLOWED_VIEWS:
            raise SQLRejected(f'Unknown table {table.sql()}. Use only: {", ".join(sorted(ALLOWED_VIEWS))}.')

    for func in tree.find_all(exp.Func):
        fname = (func.sql_name() if not isinstance(func, exp.Anonymous) else func.name).lower()
        if any(fname.startswith(p) for p in _BLOCKED_FUNCTION_PREFIXES):
            raise SQLRejected(f'Function {fname}() is not allowed.')

    # Cap the size of the result no matter what the model asked for.
    inner = tree.sql(dialect='postgres')
    return f'SELECT * FROM ({inner}) AS q LIMIT {MAX_ROWS + 1}'
