"""Static checks on model-written SQL before it reaches the database.

This is the second layer of protection. The first, and the real guarantee, is the
`mimelee_agent` database role: read-only, SELECT on the `agent` views only, 5s
timeout. This layer makes bad queries fail fast with a message the model can learn
from, and keeps anything odd from reaching Postgres even if the role were
misconfigured.

Functions are allowlisted rather than denylisted: a denylist has to anticipate
every dangerous function Postgres has, while an allowlist only has to know the
ones analytics actually need.
"""
import sqlglot
from django.conf import settings
from sqlglot import exp

ALLOWED_VIEWS = frozenset({
    'players', 'tournaments', 'sets', 'player_sets', 'placements', 'pr_seasons', 'pr_rankings',
})

ALLOWED_FUNCTIONS = frozenset({
    # aggregates and windows
    'count', 'sum', 'avg', 'min', 'max', 'stddev', 'stddev_pop', 'stddev_samp', 'variance',
    'bool_and', 'bool_or', 'logical_and', 'logical_or', 'string_agg', 'array_agg', 'group_concat',
    'percentile_cont', 'percentile_disc', 'median', 'mode', 'count_if',
    'row_number', 'rank', 'dense_rank', 'percent_rank', 'cume_dist', 'ntile',
    'lag', 'lead', 'first_value', 'last_value', 'nth_value', 'first', 'last',
    # numbers
    'round', 'floor', 'ceil', 'ceiling', 'abs', 'mod', 'power', 'pow', 'sqrt', 'trunc', 'sign',
    # text
    'lower', 'upper', 'length', 'char_length', 'trim', 'ltrim', 'rtrim', 'btrim', 'substring', 'substr',
    'left', 'right', 'concat', 'concat_ws', 'replace', 'position', 'strpos', 'str_position',
    'split_part', 'initcap', 'regexp_replace', 'regexp_like', 'starts_with',
    # dates
    'extract', 'date_part', 'date_trunc', 'timestamp_trunc', 'datetrunc', 'to_char', 'to_date',
    'age', 'current_date', 'current_timestamp', 'now', 'make_date', 'date_add', 'date_sub',
    'date_diff', 'datediff', 'ts_or_ds_to_date', 'time_to_str', 'str_to_time', 'str_to_date',
    # conditionals and casts (sqlglot represents these as functions too)
    'coalesce', 'nullif', 'greatest', 'least', 'case', 'if', 'cast', 'try_cast', 'and', 'or', 'xor',
    'not', 'in', 'between', 'exists', 'any', 'all', 'array', 'struct',
})

# Every node type that changes data, schema, session state or locks rows.
_BLOCKED_NODES = tuple(t for t in (
    getattr(exp, n, None) for n in (
        'Insert', 'Update', 'Delete', 'Merge', 'Create', 'Drop', 'Alter', 'AlterTable',
        'TruncateTable', 'Command', 'Set', 'Use', 'Grant', 'Revoke', 'Copy', 'Transaction',
        'Commit', 'Rollback', 'Lock', 'LoadData', 'Into', 'Pragma', 'Analyze', 'Describe',
    )) if t is not None)


class SQLRejected(ValueError):
    """The query is not allowed. The message is written for the model to read and fix."""


def max_rows():
    return settings.AGENT_MAX_TOOL_ROWS


def check_sql(sql):
    """Return a safe, row-limited version of `sql` or raise SQLRejected."""
    if not isinstance(sql, str) or not sql.strip():
        raise SQLRejected('Empty query.')
    if len(sql) > 4000:
        raise SQLRejected('Query is too long; simplify it.')

    try:
        statements = [s for s in sqlglot.parse(sql, read='postgres') if s is not None]
    except sqlglot.errors.SqlglotError as exc:
        raise SQLRejected(f'Could not parse the SQL: {str(exc).splitlines()[0]}') from exc
    if len(statements) != 1:
        raise SQLRejected('Send exactly one SELECT statement (no semicolon-separated statements).')
    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        raise SQLRejected('Only SELECT queries (optionally with WITH ...) are allowed.')

    for node in tree.walk():
        if isinstance(node, _BLOCKED_NODES):
            raise SQLRejected(f'{node.key.upper()} is not allowed; this is a read-only SELECT tool.')

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        schema = (table.db or '').lower()
        if not name:
            raise SQLRejected('Table functions are not allowed; select from the views.')
        if name in cte_names and not schema:
            continue
        if schema not in ('', 'agent') or name not in ALLOWED_VIEWS:
            raise SQLRejected(f'Unknown table {table.sql()}. Use only: {", ".join(sorted(ALLOWED_VIEWS))}.')

    for func in tree.find_all(exp.Func):
        fname = (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()
        if fname not in ALLOWED_FUNCTIONS:
            raise SQLRejected(f'Function {fname}() is not allowed.')

    # Cap the size of the result no matter what the model asked for.
    inner = tree.sql(dialect='postgres')
    return f'SELECT * FROM ({inner}) AS q LIMIT {max_rows() + 1}'
