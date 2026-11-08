"""Import a published ranking list as a PR season.

    python manage.py import_pr_season --region National --name "SSBMRank 2025" \
        --wiki-page SSBMRank_2025 --overrides main/data/ranking_overrides.csv --dry-run

Works for any region and either source (a SmashWiki page or a CSV with rank and
tag columns). Every row goes into RankingListEntry; only rows matched to a
player go into pr_season_results. Re-running is safe, and it never deletes.

Workflow: dry run, read the report, add `tag,player_id` lines to the overrides
file for anything wrong or unresolved, then run again without --dry-run.
"""
import csv
import datetime
import html
import json
import re
from collections import defaultdict

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Q

from main.models import Player, PRSeason, PRSeasonResult, RankingListEntry, Region, Set

WIKI_API = 'https://www.ssbwiki.com/api.php'
WIKI_USER_AGENT = 'MIMeleeStats PR season import (mimeleestats.com)'
ROW_TEMPLATE = '{{PowerRankingsRow'
# Longest rank pr_season_results can hold.
RESULT_RANK_MAX = 3

# Hand-typed national ranks in Player.name, e.g. "Ossify (#20, SSBM Rank 2025)",
# "SFAT (SSBMRank 2022 #27)", "Akir (#37, SSBM Summer 2024)".
_ANNOTATION_PATTERNS = (
    (re.compile(r'\(#(?P<rank>\d+),\s*SSBM\s*Rank\s*(?P<year>\d{4})\)\s*$'), False),
    (re.compile(r'\(SSBMRank\s*(?P<year>\d{4})\s*#(?P<rank>\d+)\)\s*$'), False),
    (re.compile(r'\(#(?P<rank>\d+),\s*SSBM Summer\s*(?P<year>\d{4})\)\s*$'), True),
)
# Any trailing "(... #N ...)" note, including regional ones like "(Chicago #9)".
_ANY_RANK_NOTE = re.compile(r'\s*\([^()]*#\d+[^()]*\)\s*$')
_SSBMRANK_NAME = re.compile(r'^SSBMRank\s+(?P<summer>Summer\s+)?(?P<year>\d{4})$', re.I)


def fetch_wikitext(page, section=None):
    params = {'action': 'parse', 'page': page, 'prop': 'wikitext',
              'format': 'json', 'redirects': 1}
    if section is not None:
        params['section'] = section
    response = requests.get(WIKI_API, params=params,
                            headers={'User-Agent': WIKI_USER_AGENT}, timeout=30)
    response.raise_for_status()
    data = response.json()
    if 'error' in data:
        raise CommandError(f"SmashWiki: {data['error'].get('info', data['error'])}")
    return data['parse']['wikitext']['*']


def _split_template_args(body):
    """Split on `|`, ignoring pipes nested inside {{...}} or [[...]]."""
    args, current, depth, i = [], [], 0, 0
    while i < len(body):
        pair = body[i:i + 2]
        if pair in ('{{', '[['):
            depth += 1
            current.append(pair)
            i += 2
        elif pair in ('}}', ']]'):
            depth -= 1
            current.append(pair)
            i += 2
        elif body[i] == '|' and depth == 0:
            args.append(''.join(current))
            current = []
            i += 1
        else:
            current.append(body[i])
            i += 1
    args.append(''.join(current))
    return args


def _clean_wiki_text(value):
    value = re.sub(r'<ref.*?(</ref>|/>)', '', value, flags=re.S)
    link = re.fullmatch(r'\s*\[\[(?:[^|\]]*\|)?([^\]]*)\]\]\s*', value)
    if link:
        value = link.group(1)
    template = re.fullmatch(r'\s*\{\{\w+\|([^|}]*).*\}\}\s*', value, flags=re.S)
    if template:
        value = template.group(1)
    return html.unescape(value).strip()


def _parse_score(value):
    try:
        return float((value or '').replace(',', '').strip())
    except ValueError:
        return None


def parse_wiki_rows(wikitext):
    """Every {{PowerRankingsRow|rank|tag|previous|...|score=N}} in the page."""
    wikitext = re.sub(r'<!--.*?-->', '', wikitext, flags=re.S)
    rows, position = [], 0
    while True:
        start = wikitext.find(ROW_TEMPLATE, position)
        if start < 0:
            return rows
        depth, i = 0, start
        while i < len(wikitext):
            pair = wikitext[i:i + 2]
            if pair == '{{':
                depth += 1
                i += 2
            elif pair == '}}':
                depth -= 1
                i += 2
                if depth == 0:
                    break
            else:
                i += 1
        raw = wikitext[start:i]
        position = i

        positional, named = [], {}
        for arg in _split_template_args(raw[len(ROW_TEMPLATE):-2])[1:]:
            key = re.match(r'\s*([a-zA-Z_]\w*)\s*=(.*)$', arg, flags=re.S)
            if key:
                named[key.group(1).lower()] = key.group(2).strip()
            else:
                positional.append(arg)
        if len(positional) < 2:
            raise CommandError(f'Could not read this row: {raw}')
        rows.append({
            'rank': positional[0].strip(),
            'tag': _clean_wiki_text(positional[1]),
            'previous_rank': _clean_wiki_text(positional[2]) if len(positional) > 2 else '',
            'score': _parse_score(html.unescape(named.get('score', ''))),
            'raw_row': raw,
        })


def parse_wiki_period(wikitext):
    """(start, end) from the infobox `period`, or (None, None)."""
    match = re.search(r'^\|\s*period\s*=\s*(.+?)\s*$', wikitext, flags=re.M)
    if not match:
        return None, None
    parts = re.split(r'\s+(?:-|–|—|&ndash;|to)\s+', match.group(1))
    if len(parts) != 2:
        return None, None
    try:
        return tuple(_parse_date(re.sub(r'(?<=\d)(st|nd|rd|th)\b', '', part)) for part in parts)
    except ValueError:
        return None, None


def _parse_date(value):
    return datetime.datetime.strptime(value.strip(), '%B %d, %Y').date()


def _iso_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise CommandError(f'Dates must be YYYY-MM-DD, got: {value}')


def parse_csv_rows(path):
    with open(path, newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        missing = {'rank', 'tag'} - set(reader.fieldnames or ())
        if missing:
            raise CommandError(f'{path} needs a header with: {", ".join(sorted(missing))}')
        return [{
            'rank': (row['rank'] or '').strip(),
            'tag': (row['tag'] or '').strip(),
            'previous_rank': (row.get('previous_rank') or '').strip(),
            'score': _parse_score(row.get('score')),
            'raw_row': json.dumps(row, ensure_ascii=False),
        } for row in reader]


def load_overrides(path):
    """{tag (casefolded): player id, or None to leave the tag unmatched}."""
    if not path:
        return {}
    with open(path, newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(line for line in handle if not line.startswith('#'))
        if not {'tag', 'player_id'} <= set(reader.fieldnames or ()):
            raise CommandError(f'{path} needs a header with: tag,player_id')
        overrides = {}
        for row in reader:
            value = (row['player_id'] or '').strip()
            if value and not value.isdigit():
                raise CommandError(f"Bad player_id for {row['tag']}: {value}")
            overrides[row['tag'].strip().casefold()] = int(value) if value else None
    known = set(Player.objects.filter(
        id__in=[v for v in overrides.values() if v]).values_list('id', flat=True))
    unknown = {v for v in overrides.values() if v} - known
    if unknown:
        raise CommandError(f'Overrides name players that do not exist: {sorted(unknown)}')
    return overrides


def strip_rank_note(name):
    return _ANY_RANK_NOTE.sub('', name or '').strip()


def parse_annotation(name):
    """(year, is_summer, rank) from a hand-typed national rank in a name, else None."""
    for pattern, is_summer in _ANNOTATION_PATTERNS:
        match = pattern.search(name or '')
        if match:
            return int(match.group('year')), is_summer, match.group('rank')
    return None


class PlayerMatcher:
    """Finds the Player for a tag on a list, strongest evidence first."""

    def __init__(self, season_name, overrides):
        self.overrides = overrides
        self.names = {}
        self.by_tag = defaultdict(list)
        self.by_annotation = defaultdict(list)
        self.main_account = {}
        for pid, name, main_id in Player.objects.values_list('id', 'name', 'main_account_id'):
            self.names[pid] = name or ''
            self.main_account[pid] = main_id
            self.by_tag[strip_rank_note(name).casefold()].append(pid)
            annotation = parse_annotation(name)
            if annotation:
                self.by_annotation[annotation].append(pid)
        self.annotated = {p for ids in self.by_annotation.values() for p in ids}

        listed = _SSBMRANK_NAME.match(season_name.strip())
        self.list_key = (int(listed.group('year')), bool(listed.group('summer'))) if listed else None

        # Tags already resolved on other lists follow a player through renames.
        self.known_tags = defaultdict(set)
        for tag, pid in (RankingListEntry.objects.exclude(player=None)
                         .exclude(pr_season__name=season_name)
                         .values_list('source_tag', 'player_id')):
            self.known_tags[tag.casefold()].add(pid)

    def match(self, tag, rank):
        """(player id or None, how, candidate ids)."""
        key = tag.casefold()
        if key in self.overrides:
            override = self.overrides[key]
            return override, ('override' if override else 'override_blank'), []

        # 1. The name already carries this exact list and rank.
        if self.list_key and rank.isdigit():
            pinned = self.by_annotation.get((*self.list_key, str(int(rank))), [])
            same_tag = [p for p in pinned if strip_rank_note(self.names[p]).casefold() == key]
            if len(same_tag) == 1:
                return same_tag[0], 'annotation', []
            # A rename, but only if nobody holds this exact tag: hand-typed ranks
            # can carry the wrong year.
            if len(pinned) == 1 and not same_tag and not self.by_tag.get(key):
                return pinned[0], 'annotation_other_name', []

        # 2. A previously imported list settled this tag.
        known = self.known_tags.get(key, ())
        if len(known) == 1:
            return next(iter(known)), 'earlier_list', []

        candidates = self.by_tag.get(key, [])
        if not candidates:
            return None, 'not_found', []
        if len(candidates) == 1:
            return candidates[0], 'tag', []

        # 3. Duplicates: the account carrying a national rank is the real one.
        annotated = [p for p in candidates if p in self.annotated]
        if len(annotated) == 1:
            return annotated[0], 'annotated_account', []
        mains = {self.main_account[p] or p for p in candidates}
        if len(mains) == 1:
            return next(iter(mains)), 'tag', []
        return None, 'ambiguous', candidates


class Command(BaseCommand):
    help = 'Import a published ranking list as a PR season for any region (SmashWiki or CSV).'

    def add_arguments(self, parser):
        parser.add_argument('--region', required=True, help='Region name or id, e.g. National')
        parser.add_argument('--name', required=True, help='Season name, e.g. "SSBMRank 2025"')
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument('--wiki-page', help='SmashWiki page title, e.g. SSBMRank_2025')
        source.add_argument('--csv', help='CSV with rank and tag columns (score, previous_rank optional)')
        parser.add_argument('--section', type=int, help='Only this section of the wiki page')
        parser.add_argument('--start', help='Season start, YYYY-MM-DD (default: the wiki infobox)')
        parser.add_argument('--end', help='Season end, YYYY-MM-DD (default: the wiki infobox)')
        parser.add_argument('--overrides', help='CSV of tag,player_id; a blank player_id leaves the tag unmatched')
        parser.add_argument('--update-dates', action='store_true',
                            help="Replace an existing season's dates; otherwise only empty dates are filled")
        parser.add_argument('--dry-run', action='store_true', help='Report only, write nothing')

    def handle(self, *args, **options):
        # Tags are full of characters a Windows console can't print.
        reconfigure = getattr(getattr(self.stdout, '_out', None), 'reconfigure', None)
        if reconfigure:
            reconfigure(errors='backslashreplace')

        region = self._get_region(options['region'])
        start = _iso_date(options['start']) if options['start'] else None
        end = _iso_date(options['end']) if options['end'] else None

        if options['wiki_page']:
            wikitext = fetch_wikitext(options['wiki_page'], options['section'])
            rows = parse_wiki_rows(wikitext)
            wiki_start, wiki_end = parse_wiki_period(wikitext)
            start, end = start or wiki_start, end or wiki_end
        else:
            rows = parse_csv_rows(options['csv'])
        self._validate_rows(rows)

        name = options['name'].strip()
        season = PRSeason.objects.filter(name=name).first()
        if season and season.region_code_id not in (None, region.pk):
            raise CommandError(f'"{name}" already exists in another region ({season.region_code}).')

        matcher = PlayerMatcher(name, load_overrides(options['overrides']))
        plan = [(row, *matcher.match(row['tag'], row['rank'])) for row in rows]
        duplicates = self._drop_duplicate_players(plan)

        self._report(plan, duplicates, matcher, name, region, season, start, end)
        if options['dry_run']:
            self.stdout.write('\nDry run: nothing was written.')
            return

        with transaction.atomic():
            summary = self._apply(season, name, region, start, end, plan, options['update_dates'])
        self.stdout.write('\nDone: ' + ', '.join(f'{v} {k}' for k, v in summary.items()) + '.')

    @staticmethod
    def _get_region(value):
        lookup = Q(pk=int(value)) if value.isdigit() else Q(name__iexact=value)
        region = Region.objects.filter(lookup).first()
        if not region:
            raise CommandError(f'No region named {value}.')
        return region

    @staticmethod
    def _validate_rows(rows):
        if not rows:
            raise CommandError('The source has no ranking rows.')
        seen = set()
        for row in rows:
            if not row['rank'] or not row['tag']:
                raise CommandError(f'Row is missing a rank or tag: {row["raw_row"]}')
            if row['tag'].casefold() in seen:
                raise CommandError(f'Tag appears twice on the list: {row["tag"]}')
            seen.add(row['tag'].casefold())

    @staticmethod
    def _drop_duplicate_players(plan):
        """pr_season_results allows a player once per season; first row wins."""
        seen, duplicates = {}, []
        for i, (row, player_id, how, candidates) in enumerate(plan):
            if player_id is None:
                continue
            if player_id in seen:
                duplicates.append((row['tag'], seen[player_id], player_id))
                plan[i] = (row, None, 'duplicate_player', candidates)
            else:
                seen[player_id] = row['tag']
        return duplicates

    def _report(self, plan, duplicates, matcher, name, region, season, start, end):
        write = self.stdout.write
        write(f'{name} | region {region} | {start} to {end} | '
              f'{"existing season id " + str(season.pk) if season else "new season"} | {len(plan)} rows')

        counts = defaultdict(int)
        for _, _, how, _ in plan:
            counts[how] += 1
        for how, count in sorted(counts.items()):
            write(f'  {how}: {count}')

        involved = [p for _, player_id, how, candidates in plan
                    for p in ([player_id] if how in ('tag', 'annotation_other_name', 'earlier_list') and player_id else candidates)]
        set_counts = self._set_counts(involved)

        def describe(pid):
            return f'{pid} "{matcher.names.get(pid, "?")}" ({set_counts.get(pid, 0)} sets)'

        sections = (
            ('annotation_other_name', 'Annotation says this rank, under a different name (check)'),
            ('tag', 'Matched on tag alone, no annotation (check low set counts)'),
            ('ambiguous', 'Ambiguous, needs an override (stored without a player)'),
            ('not_found', 'Not found (stored without a player)'),
            ('duplicate_player', 'Second tag for a player already on this list (stored without a player)'),
        )
        for how, title in sections:
            rows = [item for item in plan if item[2] == how]
            if not rows:
                continue
            write(f'\n{title}:')
            for row, player_id, _, candidates in rows:
                detail = ''
                if player_id:
                    detail = describe(player_id)
                elif candidates:
                    detail = '; '.join(describe(p) for p in sorted(
                        candidates, key=lambda p: -set_counts.get(p, 0)))
                write(f'  {row["rank"]:>4} {row["tag"]}  {detail}'.rstrip())
        for tag, kept, player_id in duplicates:
            write(f'  Note: {tag} is the same player as {kept} ({player_id}).')

    @staticmethod
    def _set_counts(player_ids):
        ids = set(player_ids)
        if not ids:
            return {}
        counts = defaultdict(int)
        for column in ('player1_id', 'player2_id'):
            for row in (Set.objects.filter(**{f'{column}__in': ids})
                        .values(column).annotate(n=Count('id'))):
                counts[row[column]] += row['n']
        return counts

    def _apply(self, season, name, region, start, end, plan, update_dates):
        summary = defaultdict(int)
        if season is None:
            season = PRSeason.objects.create(name=name, region_code=region, start_date=start,
                                             end_date=end, is_active=False)
            summary['season created'] = 1
        else:
            changed = []
            if season.region_code_id is None:
                season.region_code = region
                changed.append('region_code')
            for field, value in (('start_date', start), ('end_date', end)):
                if value and getattr(season, field) != value and (update_dates or getattr(season, field) is None):
                    setattr(season, field, value)
                    changed.append(field)
                elif value and getattr(season, field) != value:
                    self.stdout.write(f'Kept existing {field} {getattr(season, field)}; '
                                      f'source says {value} (use --update-dates).')
            if changed:
                season.save(update_fields=changed)
                summary['season fields updated'] = len(changed)

        existing_raw = {e.source_tag: e for e in RankingListEntry.objects.filter(pr_season=season)}
        existing_results = {r.player_id: r for r in PRSeasonResult.objects.filter(pr_season=season)}

        for row, player_id, how, _ in plan:
            entry = existing_raw.get(row['tag'])
            previous_player = entry.player_id if entry else None
            if player_id is None and how != 'override_blank':
                player_id = previous_player     # never lose an earlier match

            RankingListEntry.objects.update_or_create(
                pr_season=season, source_tag=row['tag'],
                defaults={'player_id': player_id, 'rank': row['rank'],
                          'previous_rank': row['previous_rank'], 'score': row['score'],
                          'raw_row': row['raw_row']},
            )
            summary['raw rows saved'] += 1

            if previous_player and previous_player != player_id:
                self.stdout.write(f'Check by hand: {row["tag"]} moved from player {previous_player} '
                                  f'to {player_id}; the old result row was left in place.')
            if player_id is None:
                continue
            rank = row['rank']
            result = existing_results.get(player_id)
            if result:
                if result.rank != rank:
                    self.stdout.write(f'Left as is: {row["tag"]} already has rank {result.rank}, '
                                      f'source says {rank}.')
                continue
            if len(rank) > RESULT_RANK_MAX:
                self.stdout.write(f'Skipped result for {row["tag"]}: rank "{rank}" is too long.')
                continue
            existing_results[player_id] = PRSeasonResult.objects.create(
                pr_season=season, player_id=player_id, rank=rank)
            summary['results added'] += 1
        return summary
