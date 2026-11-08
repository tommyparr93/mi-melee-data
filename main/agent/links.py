"""Adds player and tournament links to a finished answer.

The model was unreliable at this, linking some names in a list and not others. The
tool results already say which id goes with which name, so plain code can do it the
same way every time. A name only gets a link when it points to exactly one id in
this turn's results, because tags are not unique.
"""
import json
import re

_MARKDOWN_LINK = r'\[[^\]]*\]\([^)]*\)'
_LINK_WITHOUT_ID = re.compile(r'\[([^\]]+)\]\(/(?:player|tournaments)/(?:0/?)?\)')
_ROW_PAIRS = (('player_id', 'player', 'player'), ('opponent_id', 'opponent', 'player'),
              ('a_id', 'a', 'player'), ('b_id', 'b', 'player'),
              ('tournament_id', 'tournament', 'tournament'))
_PLAYER_KEYS = {'player', 'player_a', 'player_b', 'players'}
_TOURNAMENT_KEYS = {'tournament', 'tournaments', 'biggest_michigan_events'}
_SQL_PLAYER_COLUMNS = {'player', 'opponent', 'winner', 'loser', 'player1', 'player2'}
_RANK_SUFFIX = re.compile(r'\s*\(.*\)\s*$')
# "[Ossify](/player/282043/) (player_id 282043)": an id repeated right after its own link.
_ID_AFTER_LINK = re.compile(r'(\[[^\]]+\]\(/(?:player|tournaments)/(\d+)/?\)\*{0,2})\s*\((?:(?:player_|tournament_)?id)?[\s:#]*\2\)')


def _url(kind, row_id):
    return f'/player/{row_id}/' if kind == 'player' else f'/tournaments/{row_id}'


def _add(found, kind, row_id, name):
    if not row_id or not isinstance(name, str):
        return
    url = _url(kind, row_id)
    # The site shows "Zain (#1, SSBMRank 2025)" but answers usually say "Zain".
    for text in {name.strip(), _RANK_SUFFIX.sub('', name).strip()}:
        if len(text) > 1 and not set(text) & set('[]()*'):
            found.setdefault(text, set()).add(url)


def _collect_sql(node, found):
    columns = node.get('columns') or []
    for name in columns:
        id_column = f'{name}_id'
        if id_column in columns and (name in _SQL_PLAYER_COLUMNS or name == 'tournament'):
            kind = 'tournament' if name == 'tournament' else 'player'
            for row in node.get('rows') or []:
                _add(found, kind, row[columns.index(id_column)], row[columns.index(name)])


def _walk(node, key, found):
    if isinstance(node, list):
        for item in node:
            _walk(item, key, found)
    elif isinstance(node, dict):
        for id_key, name_key, kind in _ROW_PAIRS:
            _add(found, kind, node.get(id_key), node.get(name_key))
        if key in _PLAYER_KEYS:
            _add(found, 'player', node.get('id'), node.get('name'))
        elif key in _TOURNAMENT_KEYS:
            _add(found, 'tournament', node.get('id'), node.get('name'))
        _collect_sql(node, found)
        for child_key, value in node.items():
            _walk(value, child_key, found)


def add_links(answer, tool_calls):
    """Return `answer` with every unambiguous name from `tool_calls` linked."""
    found = {}
    for call in tool_calls:
        try:
            _walk(json.loads(call.result), None, found)
        except json.JSONDecodeError:         # a result cut off for length
            continue
    answer = _LINK_WITHOUT_ID.sub(r'\1', answer)
    links = {name: urls.pop() for name, urls in found.items() if len(urls) == 1}
    if not links:
        return answer
    names = '|'.join(re.escape(n) for n in sorted(links, key=len, reverse=True))
    pattern = re.compile(rf'(?<![\w#@])({names})(?!\w)')
    pieces = re.split(f'({_MARKDOWN_LINK})', answer)
    for i in range(0, len(pieces), 2):           # odd positions are existing links
        pieces[i] = pattern.sub(lambda m: f'[{m.group(1)}]({links[m.group(1)]})', pieces[i])
    return _ID_AFTER_LINK.sub(r'\1', ''.join(pieces))
