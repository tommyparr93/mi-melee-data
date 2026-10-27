"""Core logic tests.

Focus: the pure stats math (win/loss/rate, head-to-head), the query-param
parser used across analytics, and the caching freshness contract (the
highest-risk Tier-1 change — a stale cache would be a correctness bug, so
its data-version invalidation is locked down here).
"""
from django.test import TestCase, SimpleTestCase, RequestFactory
from django.core.cache import cache
from django.http import HttpResponse
from django.contrib.auth import get_user_model
from django.urls import reverse

from main.models import Player, Tournament, Set, PRSeason, PRSeasonResult
from main.views import (
    player_detail_calculations,
    get_head_to_head_results,
    _parse_int_param,
    _data_version,
    cached_partial,
    _rank_sort_key,
)


class _RankStub:
    def __init__(self, rank):
        self.rank = rank


class RankSortKeyTests(SimpleTestCase):
    """Locks the PR rank order: numbers ascending by value (not string),
    then text ranks (HM before IM, as the published rankings list them), then any other text alphabetically."""

    def _sorted(self, ranks):
        return [r.rank for r in sorted((_RankStub(x) for x in ranks),
                                       key=_rank_sort_key)]

    def test_numeric_orders_by_value_not_string(self):
        self.assertEqual(self._sorted(['10', '2', '1', '3']),
                         ['1', '2', '3', '10'])

    def test_text_ranks_come_after_numbers(self):
        self.assertEqual(self._sorted(['IM', '2', 'HM', '1', '10']),
                         ['1', '2', '10', 'HM', 'IM'])

    def test_unknown_text_after_known_alphabetical(self):
        self.assertEqual(self._sorted(['ZZ', 'HM', 'IM']),
                         ['HM', 'IM', 'ZZ'])

    def test_blank_rank_does_not_crash(self):
        # empty/None ranks are treated as text, sorted last — must not raise
        self.assertEqual(self._sorted(['1', '', None]), ['1', '', None])


def make_tournament(tid, name="T", date="2024-01-01"):
    return Tournament.objects.create(id=tid, name=name, date=date)


def make_set(sid, p1, p2, winner, tournament, pr_eligible=True,
             s1=2, s2=0):
    return Set.objects.create(
        id=sid, player1=p1, player2=p2,
        player1_score=s1, player2_score=s2,
        winner_id=winner.id, tournament=tournament,
        played=True, pr_eligible=pr_eligible, location="Pool",
    )


class ParseIntParamTests(SimpleTestCase):
    """Used by every analytics view to read query params — bad parsing here
    silently mis-filters whole pages."""

    def setUp(self):
        self.rf = RequestFactory()

    def _param(self, qs, name, default=None):
        return _parse_int_param(self.rf.get(f"/?{qs}"), name, default)

    def test_valid_int(self):
        self.assertEqual(self._param("year=2024", "year"), 2024)

    def test_missing_returns_default(self):
        self.assertEqual(self._param("x=1", "year", default=7), 7)
        self.assertIsNone(self._param("x=1", "year"))

    def test_blank_and_all_return_default(self):
        self.assertEqual(self._param("year=", "year", default=9), 9)
        self.assertEqual(self._param("year=all", "year", default=9), 9)

    def test_non_numeric_returns_default(self):
        self.assertEqual(self._param("year=abc", "year", default=3), 3)

    def test_negative_int_parsed(self):
        self.assertEqual(self._param("season=-5", "season"), -5)


class PlayerDetailCalculationsTests(TestCase):

    def setUp(self):
        self.p = Player.objects.create(name="Main")
        self.o1 = Player.objects.create(name="Opp1")
        self.o2 = Player.objects.create(name="Opp2")
        self.t1 = make_tournament(1, "Tourney 1")
        self.t2 = make_tournament(2, "Tourney 2")

    def test_basic_record_and_rates(self):
        sets = [
            make_set(1, self.p, self.o1, self.p, self.t1),   # W
            make_set(2, self.p, self.o2, self.o2, self.t1),  # L
            make_set(3, self.o1, self.p, self.p, self.t2),   # W
        ]
        calc = player_detail_calculations(self.p, sets)
        self.assertEqual(calc['wins'], 2)
        self.assertEqual(calc['losses'], 1)
        self.assertEqual(calc['set_count'], 3)
        self.assertEqual(calc['win_rate'], int(2 / 3 * 100))
        self.assertEqual(calc['loss_rate'], 100 - int(2 / 3 * 100))
        self.assertEqual(calc['tournament_count'], 2)
        self.assertEqual(calc['recent_form'], ['W', 'L', 'W'])

    def test_zero_sets_no_division_error(self):
        calc = player_detail_calculations(self.p, [])
        self.assertEqual(calc['set_count'], 0)
        self.assertEqual(calc['wins'], 0)
        self.assertEqual(calc['losses'], 0)
        self.assertEqual(calc['win_rate'], 0)
        self.assertEqual(calc['recent_form'], [])

    def test_recent_form_capped_at_five(self):
        sets = [make_set(10 + i, self.p, self.o1, self.p, self.t1)
                for i in range(8)]
        calc = player_detail_calculations(self.p, sets)
        self.assertEqual(len(calc['recent_form']), 5)


class HeadToHeadTests(TestCase):

    def setUp(self):
        self.p = Player.objects.create(name="Main")
        self.a = Player.objects.create(name="Alpha", pr_notable=True)
        self.b = Player.objects.create(name="Bravo", pr_notable=False)
        self.t = make_tournament(1)

    def test_records_filtering_and_sort(self):
        sets = [
            make_set(1, self.p, self.a, self.p, self.t),                 # vs A: W
            make_set(2, self.a, self.p, self.a, self.t),                 # vs A: L
            make_set(3, self.p, self.b, self.b, self.t),                 # vs B: L
            make_set(4, self.p, self.a, self.p, self.t,
                     pr_eligible=False),                                  # excluded
        ]
        results = get_head_to_head_results(self.p, sets)
        by_id = {r['opponent'].id: r for r in results}

        self.assertEqual(by_id[self.a.id]['wins'], 1)
        self.assertEqual(by_id[self.a.id]['losses'], 1)
        self.assertEqual(by_id[self.a.id]['count'], 2)
        self.assertEqual(by_id[self.a.id]['win_rate'], 50)
        self.assertTrue(by_id[self.a.id]['pr_notable'])

        self.assertEqual(by_id[self.b.id]['count'], 1)
        self.assertEqual(by_id[self.b.id]['losses'], 1)

        # Sorted by set count desc → A (2) before B (1)
        self.assertEqual(results[0]['opponent'].id, self.a.id)
        # The player themselves is never an opponent row
        self.assertNotIn(self.p.id, by_id)


class DataVersionCacheTests(TestCase):
    """The caching freshness guarantee: a new tournament/set MUST change the
    data-version token so cached pages can't serve stale data."""

    def setUp(self):
        cache.clear()
        self.p1 = Player.objects.create(name="P1")
        self.p2 = Player.objects.create(name="P2")
        self.t = make_tournament(1)

    def tearDown(self):
        cache.clear()

    def test_token_is_string_and_changes_on_new_set(self):
        v1 = _data_version()
        self.assertIsInstance(v1, str)
        make_set(1, self.p1, self.p2, self.p1, self.t)
        self.assertNotEqual(v1, _data_version(),
                            "data version must change when a Set is added")

    def test_token_changes_on_eligibility_change(self):
        v1 = _data_version()
        Player.objects.filter(id=self.p1.id).update(pr_eligible=True)
        self.assertNotEqual(v1, _data_version())

    def test_cached_partial_serves_then_invalidates(self):
        calls = {'n': 0}

        @cached_partial(timeout=900)
        def view(request):
            calls['n'] += 1
            return HttpResponse(f"hit {calls['n']}")

        rf = RequestFactory()
        r1 = view(rf.get('/x/'))
        r2 = view(rf.get('/x/'))
        self.assertEqual(r1.content, r2.content)
        self.assertEqual(calls['n'], 1, "second identical request must be cached")

        # New data → key changes → view recomputes
        make_set(99, self.p1, self.p2, self.p1, self.t)
        r3 = view(rf.get('/x/'))
        self.assertEqual(calls['n'], 2,
                         "cache must invalidate after data changes")

    def test_cached_partial_skips_non_get(self):
        calls = {'n': 0}

        @cached_partial(timeout=900)
        def view(request):
            calls['n'] += 1
            return HttpResponse("ok")

        rf = RequestFactory()
        view(rf.post('/x/'))
        view(rf.post('/x/'))
        self.assertEqual(calls['n'], 2, "POST must never be cached")


class SeasonResultMutationTests(TestCase):
    """Phase 2: inline rank edit + remove must persist, re-sort, and be
    locked to superusers."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser('admin', 'a@x.com', 'pw')
        self.season = PRSeason.objects.create(name='S1')
        self.p1 = Player.objects.create(name='Aaa')
        self.p2 = Player.objects.create(name='Bbb')
        self.r1 = PRSeasonResult.objects.create(
            pr_season=self.season, player=self.p1, rank='10')
        self.r2 = PRSeasonResult.objects.create(
            pr_season=self.season, player=self.p2, rank='2')

    def test_update_persists_rank(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('update_pr_result', args=[self.r1.id]), {'rank': '1'})
        self.assertEqual(resp.status_code, 200)
        self.r1.refresh_from_db()
        self.assertEqual(self.r1.rank, '1')

    def test_blank_rank_is_ignored(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse('update_pr_result', args=[self.r1.id]), {'rank': '  '})
        self.r1.refresh_from_db()
        self.assertEqual(self.r1.rank, '10')  # unchanged

    def test_remove_deletes_only_target(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('remove_pr_result', args=[self.r1.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(PRSeasonResult.objects.filter(id=self.r1.id).exists())
        self.assertTrue(PRSeasonResult.objects.filter(id=self.r2.id).exists())

    def test_mutations_require_superuser(self):
        # not logged in → redirected, no change
        resp = self.client.post(
            reverse('update_pr_result', args=[self.r1.id]), {'rank': '1'})
        self.assertEqual(resp.status_code, 302)
        self.r1.refresh_from_db()
        self.assertEqual(self.r1.rank, '10')

        User = get_user_model()
        plain = User.objects.create_user('plain', 'p@x.com', 'pw')
        self.client.force_login(plain)
        resp = self.client.post(reverse('remove_pr_result', args=[self.r1.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(PRSeasonResult.objects.filter(id=self.r1.id).exists())


import csv as _csv
import os as _os
import tempfile as _tempfile
from io import StringIO as _StringIO
from unittest import mock as _mock
from django.core.management import call_command as _call_command


def _write_geo_csv(rows):
    fd, path = _tempfile.mkstemp(suffix='.csv')
    _os.close(fd)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = _csv.DictWriter(f, fieldnames=[
            'id', 'name', 'city', 'state', 'lat', 'lng',
            'venue_name', 'venue_address', 'postal_code'])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


class ImportGeocodesTests(TestCase):
    """The import must only ever touch location columns, matched by id, so it
    is safe to run against a database whose other data has moved on."""

    def _run(self, rows, *args):
        path = _write_geo_csv(rows)
        self.addCleanup(_os.remove, path)
        out = _StringIO()
        _call_command('import_geocodes', path, *args, stdout=out)
        return out.getvalue()

    def _row(self, tid, **kw):
        base = dict(id=tid, name='CSV NAME', city='CSV City', state='ZZ',
                    lat=42.1, lng=-83.7, venue_name='Venue',
                    venue_address='1 Main St', postal_code='48104')
        base.update(kw)
        return base

    def test_only_location_columns_change(self):
        Tournament.objects.create(id=1, name='Keep Me', city='Ann Arbor', state='MI')
        Tournament.objects.create(id=2, name='Blank City')
        self._run([self._row(1), self._row(2)])
        t1, t2 = Tournament.objects.get(id=1), Tournament.objects.get(id=2)
        self.assertEqual((t1.lat, t1.lng, t1.venue_name), (42.1, -83.7, 'Venue'))
        self.assertEqual((t1.name, t1.city, t1.state), ('Keep Me', 'Ann Arbor', 'MI'))
        # blank city/state are filled, but names are never touched
        self.assertEqual((t2.city, t2.state, t2.name), ('CSV City', 'ZZ', 'Blank City'))

    def test_existing_coordinates_kept_unless_forced(self):
        Tournament.objects.create(id=3, name='T', lat=1.0, lng=2.0)
        self._run([self._row(3, lat=9.0, lng=9.0)])
        t = Tournament.objects.get(id=3)
        self.assertEqual((t.lat, t.lng), (1.0, 2.0))
        self._run([self._row(3, lat=9.0, lng=9.0)], '--force')
        t.refresh_from_db()
        self.assertEqual((t.lat, t.lng), (9.0, 9.0))

    def test_unknown_ids_and_bad_rows_are_skipped(self):
        Tournament.objects.create(id=4, name='T')
        out = self._run([self._row(999), self._row(4, lat='abc')])
        self.assertIn('id not in this database: 1', out)
        self.assertIn('bad CSV rows: 1', out)
        self.assertIsNone(Tournament.objects.get(id=4).lat)

    def test_dry_run_writes_nothing(self):
        Tournament.objects.create(id=6, name='T')
        out = self._run([self._row(6)], '--dry-run')
        self.assertIn('Would update 1', out)
        self.assertIsNone(Tournament.objects.get(id=6).lat)


class PullStartggLocationsSafetyTests(TestCase):
    """Production city/state may be hand-corrected: the Start.gg pull must not
    overwrite them unless explicitly asked."""

    PAYLOAD = {'data': {'event': {'tournament': {
        'lat': 42.0, 'lng': -83.0, 'venueName': 'V', 'venueAddress': 'A',
        'postalCode': '48000', 'addrState': 'OH', 'city': 'Start.gg City'}}}}

    def _run(self, *args):
        resp = _mock.Mock(status_code=200)
        resp.json.return_value = self.PAYLOAD
        base = 'main.management.commands.pull_startgg_locations'
        with _mock.patch.dict(_os.environ, {'SMASHGG_TOKEN': 'x'}), \
                _mock.patch('environ.Env.read_env'), \
                _mock.patch(base + '.requests.post', return_value=resp), \
                _mock.patch(base + '.time.sleep'):
            _call_command('pull_startgg_locations', *args, stdout=_StringIO())

    def test_city_state_not_overwritten_by_default(self):
        Tournament.objects.create(id=5, name='T', city='Hand Edited', state='MI')
        self._run()
        t = Tournament.objects.get(id=5)
        self.assertEqual((t.city, t.state), ('Hand Edited', 'MI'))
        self.assertEqual((t.lat, t.lng, t.venue_name), (42.0, -83.0, 'V'))

    def test_overwrite_text_flag_replaces_them(self):
        Tournament.objects.create(id=5, name='T', city='Hand Edited', state='MI')
        self._run('--overwrite-text')
        t = Tournament.objects.get(id=5)
        self.assertEqual((t.city, t.state), ('Start.gg City', 'OH'))


class SeasonAdminGatingTests(TestCase):
    """Admin-only season tools must send logged-out users to the admin login
    (the project has no /accounts/login/ route) and refuse non-superusers."""

    def test_anonymous_redirected_to_admin_login(self):
        resp = self.client.get('/seasons/')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].startswith('/admin/login/'))
        self.assertIn('next=/seasons/', resp['Location'])

    def test_non_superuser_forbidden_superuser_allowed(self):
        User = get_user_model()
        plain = User.objects.create_user('plain2', 'p2@x.com', 'pw')
        self.client.force_login(plain)
        self.assertEqual(self.client.get('/seasons/').status_code, 403)
        admin = User.objects.create_superuser('admin2', 'a2@x.com', 'pw')
        self.client.force_login(admin)
        self.assertEqual(self.client.get('/seasons/').status_code, 200)


import datetime as _dt


class SyncMiTournamentsTests(TestCase):
    """The daily cron job crashed every run with "'datetime.date' object has
    no attribute 'timestamp'" (Tournament.date is a DateField). These lock in
    the default-date path plus the new --dry-run."""

    BASE = 'main.management.commands.sync_mi_tournaments'

    def _api(self, nodes):
        resp = _mock.Mock(status_code=200)
        resp.json.return_value = {'data': {'tournaments': {
            'pageInfo': {'totalPages': 1}, 'nodes': nodes}}}
        return resp

    def _node(self, event_id=777):
        return {
            'id': 1, 'name': 'Test Cup', 'slug': 'tournament/test-cup',
            'startAt': 1700000000, 'isOnline': False,
            'events': [{'id': event_id, 'name': 'Melee Singles',
                        'slug': 'tournament/test-cup/event/melee-singles',
                        'type': 1, 'numEntrants': 20, 'videogame': {'id': 1}}],
        }

    def _run(self, nodes, *args):
        out = _StringIO()
        enter = _mock.Mock()
        with _mock.patch.dict(_os.environ, {'SMASHGG_TOKEN': 'x'}), \
                _mock.patch('environ.Env.read_env'), \
                _mock.patch(self.BASE + '.requests.post', return_value=self._api(nodes)), \
                _mock.patch(self.BASE + '.time.sleep'), \
                _mock.patch(self.BASE + '.enter_tournament', enter):
            _call_command('sync_mi_tournaments', *args, stdout=out)
        return out.getvalue(), enter

    def test_default_after_date_uses_latest_tournament_without_crashing(self):
        Tournament.objects.create(id=1, name='Old', date=_dt.date(2026, 6, 29))
        out, _ = self._run([])
        self.assertIn('Using date from latest DB tournament: 2026-06-28', out)
        self.assertIn('Sync complete', out)

    def test_undated_tournaments_are_ignored_for_the_default_date(self):
        Tournament.objects.create(id=1, name='Undated')            # date NULL
        Tournament.objects.create(id=2, name='Dated', date=_dt.date(2026, 6, 29))
        out, _ = self._run([])
        self.assertIn('2026-06-28', out)

    def test_new_tournament_is_ingested_and_existing_one_skipped(self):
        Tournament.objects.create(id=1, name='Old', date=_dt.date(2026, 6, 29))
        out, enter = self._run([self._node(777)])
        enter.assert_called_once()
        self.assertEqual(enter.call_args[0][0],
                         'https://start.gg/tournament/test-cup/event/melee-singles')
        Tournament.objects.create(id=777, name='Test Cup', date=_dt.date(2026, 7, 1))
        out2, enter2 = self._run([self._node(777)])
        enter2.assert_not_called()
        self.assertIn('Already in database', out2)

    def test_dry_run_imports_nothing(self):
        Tournament.objects.create(id=1, name='Old', date=_dt.date(2026, 6, 29))
        out, enter = self._run([self._node(777)], '--dry-run')
        enter.assert_not_called()
        self.assertIn('[DRY RUN] Would ingest', out)
        self.assertIn('Dry run complete: 1 tournaments would be added', out)


class PublicPrSeasonPageOrderTests(TestCase):
    """/pr_season/<id> is public and its results had no ordering at all. Rank
    is a text column, so it must sort 1, 2 ... 10, then HM, then IM."""

    def test_members_are_sorted_numerically_then_hm_then_im(self):
        season = PRSeason.objects.create(name='Order Test')
        for i, rank in enumerate(['IM', '10', 'HM', '2', '1', '11']):
            PRSeasonResult.objects.create(
                pr_season=season, player=Player.objects.create(name=f'P{i}'), rank=rank)
        resp = self.client.get(f'/pr_season/{season.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([m.rank for m in resp.context['pr_members']],
                         ['1', '2', '10', '11', 'HM', 'IM'])


from main.models import Region as _Region, Character as _Character
from main.views import (
    _season_page_context as _season_ctx,
    _sorted_season_results as _sorted_results,
    _clean_player_tag as _clean_tag,
)


class CleanPlayerTagTests(SimpleTestCase):
    def test_strips_imported_ssbm_rank_suffix(self):
        self.assertEqual(_clean_tag('Ossify (#20, SSBM Rank 2025)'), 'Ossify')
        self.assertEqual(_clean_tag('ckyulmiqnudaetr (#29, SSBM Rank 2024)'), 'ckyulmiqnudaetr')

    def test_leaves_normal_and_odd_names_alone(self):
        self.assertEqual(_clean_tag('Negat!ve'), 'Negat!ve')
        self.assertEqual(_clean_tag('mACOMBFALCO13 (bozo jr)'), 'mACOMBFALCO13 (bozo jr)')
        self.assertEqual(_clean_tag(None), '')


class SeasonPageContextTests(TestCase):
    """Movement vs the previous season, season records, grouping, and the
    season picker for the public PR season page."""

    def setUp(self):
        _Region.objects.create(id=7, name='Michigan')
        self.prev = PRSeason.objects.create(
            name='Prev', start_date=_dt.date(2025, 1, 1), end_date=_dt.date(2025, 6, 30), region_code_id=7)
        self.cur = PRSeason.objects.create(
            name='Cur', start_date=_dt.date(2025, 7, 1), end_date=_dt.date(2025, 12, 31), region_code_id=7)
        fox = _Character.objects.create(name='Fox', icon_path='/static/fox.png')
        self.p = {n: Player.objects.create(name=n, main_char=fox if n == 'A' else None) for n in 'ABCDEF'}
        for player, rank in (('A', '1'), ('B', '2'), ('C', '3'), ('D', 'HM')):
            PRSeasonResult.objects.create(pr_season=self.prev, player=self.p[player], rank=rank)
        for player, rank in (('B', '1'), ('A', '2'), ('C', '3'), ('D', '4'), ('E', '5'), ('F', 'HM')):
            PRSeasonResult.objects.create(pr_season=self.cur, player=self.p[player], rank=rank)

    def _ctx(self):
        return _season_ctx(self.cur, _sorted_results(self.cur))

    def test_grouping_and_order(self):
        ctx = self._ctx()
        self.assertEqual([e['name'] for e in ctx['podium']], ['B', 'A', 'C'])
        self.assertEqual([e['name'] for e in ctx['ranked']], ['D', 'E'])
        self.assertEqual([e['name'] for e in ctx['honorable']], ['F'])
        self.assertEqual(ctx['inactive'], [])
        self.assertEqual(ctx['ranked_count'], 5)

    def test_movement_versus_previous_season(self):
        ctx = self._ctx()
        self.assertEqual(ctx['prev_season'], self.prev)
        b, a, c = ctx['podium']
        self.assertEqual((b['move']['kind'], b['move']['value']), ('up', 1))
        self.assertEqual((a['move']['kind'], a['move']['value']), ('down', 1))
        self.assertEqual(c['move']['kind'], 'same')
        d, e = ctx['ranked']
        self.assertEqual((d['move']['kind'], d['move']['label']), ('from', 'from HM'))
        self.assertEqual(e['move']['kind'], 'new')
        self.assertIsNone(ctx['honorable'][0]['move'])      # mentions never show movement

    def test_no_previous_season_means_no_movement(self):
        ctx = _season_ctx(self.prev, _sorted_results(self.prev))
        self.assertIsNone(ctx['prev_season'])
        self.assertTrue(all(e['move'] is None for e in ctx['podium']))

    def test_season_record_counts_only_eligible_sets_at_tagged_tournaments(self):
        t = Tournament.objects.create(id=1, name='T', date=_dt.date(2025, 8, 1), pr_season=self.cur)
        other = Tournament.objects.create(id=2, name='Other', date=_dt.date(2025, 2, 1), pr_season=self.prev)
        a, b = self.p['A'], self.p['B']
        make_set(1, b, a, b, t)                          # B beats A
        make_set(2, b, a, b, t)                          # B beats A
        make_set(3, a, b, a, t)                          # A beats B
        make_set(4, b, a, b, t, pr_eligible=False)       # not PR-eligible: ignored
        make_set(5, b, a, b, other)                      # different season: ignored
        ctx = self._ctx()
        by_name = {e['name']: e for e in ctx['podium']}
        self.assertEqual((by_name['B']['wins'], by_name['B']['losses'], by_name['B']['win_pct']), (2, 1, 67))
        self.assertEqual((by_name['A']['wins'], by_name['A']['losses']), (1, 2))
        self.assertEqual(by_name['B']['events'], 1)
        self.assertIsNone(by_name['C']['win_pct'])       # no sets: no record shown

    def test_character_icon_and_name_are_exposed(self):
        a = next(e for e in self._ctx()['podium'] if e['name'] == 'A')
        self.assertEqual((a['icon'], a['char']), ('/static/fox.png', 'Fox'))

    def test_picker_includes_current_season_even_when_it_has_no_results(self):
        empty = PRSeason.objects.create(
            name='Empty', start_date=_dt.date(2026, 1, 1), end_date=_dt.date(2026, 6, 30), region_code_id=7)
        ids = [s['id'] for s in _season_ctx(empty, [])['season_nav']]
        self.assertIn(empty.id, ids)
        self.assertIn(self.cur.id, ids)

    def test_page_renders_for_a_season_and_for_an_empty_one(self):
        self.assertEqual(self.client.get(f'/pr_season/{self.cur.pk}').status_code, 200)
        empty = PRSeason.objects.create(name='Empty', start_date=_dt.date(2026, 1, 1), end_date=_dt.date(2026, 6, 30))
        resp = self.client.get(f'/pr_season/{empty.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "haven't been published yet")


from types import SimpleNamespace as _NS
from main.views import _journey_pr_history, _json_for_script


class JsonForScriptTests(SimpleTestCase):
    def test_script_breakouts_are_escaped_but_still_valid_json(self):
        import json as _json
        out = _json_for_script({'name': '</script><b>&x'})
        self.assertNotIn('<', out)
        self.assertNotIn('>', out)
        self.assertNotIn('&', out)
        self.assertEqual(_json.loads(out)['name'], '</script><b>&x')


class JourneyDataViewTests(TestCase):
    """Year filter, year list, PR tracker and tournament placements for the
    journey data partial."""

    def setUp(self):
        _Region.objects.create(id=7, name='Michigan')
        self.me = Player.objects.create(name='Me (#7, SSBM Rank 2025)')
        self.opp = Player.objects.create(name='Opp')
        self.t = {}
        for tid, date in ((1, _dt.date(2024, 3, 1)), (2, _dt.date(2025, 4, 1)), (3, _dt.date(2025, 9, 1))):
            self.t[tid] = Tournament.objects.create(
                id=tid, name=f'T{tid}', date=date, lat=42.0 + tid, lng=-83.0, online=False)
            make_set(tid, self.me, self.opp, self.me, self.t[tid])
        # a tournament without coordinates must never appear on the map
        no_coords = Tournament.objects.create(id=9, name='NoCoords', date=_dt.date(2025, 5, 1))
        make_set(9, self.me, self.opp, self.me, no_coords)

    def _get(self, qs=''):
        results = [_NS(tournament_id=1, placement=3), _NS(tournament_id=3, placement=1)]
        with _mock.patch('main.views.TournamentResults') as tr:
            tr.objects.filter.return_value = results
            return self.client.get(f'/journey/data/?player={self.me.id}{qs}')

    def test_all_time_and_year_list(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['journey_count'], 3)
        self.assertEqual(resp.context['years'], [{'year': 2024, 'count': 1}, {'year': 2025, 'count': 2}])
        self.assertIsNone(resp.context['selected_year'])
        self.assertEqual(resp.context['total_journey_count'], 3)

    def test_year_filter_narrows_the_journey_but_not_the_year_list(self):
        import json as _json
        resp = self._get('&year=2025')
        self.assertEqual(resp.context['selected_year'], 2025)
        self.assertEqual(resp.context['journey_count'], 2)
        self.assertEqual(resp.context['total_journey_count'], 3)
        self.assertEqual(len(resp.context['years']), 2)           # selector still shows every year
        payload = _json.loads(resp.context['journey_data'])
        self.assertEqual([d['name'] for d in payload], ['T2', 'T3'])
        self.assertTrue(all(d['date'].startswith('2025') for d in payload))

    def test_unknown_year_falls_back_to_all_time(self):
        resp = self._get('&year=1999')
        self.assertIsNone(resp.context['selected_year'])
        self.assertEqual(resp.context['journey_count'], 3)

    def test_placement_is_in_the_payload_for_the_wins_card(self):
        import json as _json
        payload = _json.loads(self._get().context['journey_data'])
        self.assertEqual({d['name']: d['placement'] for d in payload}, {'T1': 3, 'T2': None, 'T3': 1})

    def test_display_name_drops_the_imported_annotation(self):
        self.assertEqual(self._get().context['player_display_name'], 'Me')

    def test_renders_year_pills_and_no_pr_card_without_pr_history(self):
        resp = self._get('&year=2025')
        self.assertContains(resp, 'jy-btn')
        self.assertContains(resp, 'id="card-twins"')
        self.assertNotContains(resp, 'id="card-pr"')

    def test_renders_compact_pr_card_when_the_player_has_pr_history(self):
        season = PRSeason.objects.create(
            name='2025 Summer Power Rankings', start_date=_dt.date(2025, 4, 1),
            end_date=_dt.date(2025, 9, 30), region_code_id=7)
        PRSeasonResult.objects.create(pr_season=season, player=self.me, rank='2')
        resp = self._get()
        self.assertContains(resp, 'id="card-pr"')           # compact card, hidden until a PR season finishes
        self.assertContains(resp, '2025 Summer')                  # season name (" Power Rankings" trimmed) is in the PR data
        self.assertEqual(resp.context['pr_summary']['best']['label'], '#2')


class JourneyPrHistoryTests(TestCase):
    def setUp(self):
        _Region.objects.create(id=7, name='Michigan')
        self.p = Player.objects.create(name='P')
        self.seasons = [
            PRSeason.objects.create(name=n, start_date=s, end_date=e, region_code_id=7)
            for n, s, e in (('S1 Power Rankings', _dt.date(2023, 1, 1), _dt.date(2023, 6, 30)),
                            ('S2', _dt.date(2023, 7, 1), _dt.date(2023, 12, 31)),
                            ('S3', _dt.date(2024, 1, 1), _dt.date(2024, 6, 30)),
                            ('S4', _dt.date(2024, 7, 1), _dt.date(2024, 12, 31)))]

    def _rank(self, season, rank):
        PRSeasonResult.objects.create(pr_season=season, player=self.p, rank=rank)

    def test_no_history(self):
        self.assertEqual(_journey_pr_history(self.p), ([], None))

    def test_ordered_oldest_first_with_labels_and_tiers(self):
        self._rank(self.seasons[2], 'HM')
        self._rank(self.seasons[0], '1')
        self._rank(self.seasons[1], '5')
        seasons, _ = _journey_pr_history(self.p)
        self.assertEqual([s['short'] for s in seasons], ['S1', 'S2', 'S3'])
        self.assertEqual([s['label'] for s in seasons], ['#1', '#5', 'HM'])
        self.assertEqual([s['tier'] for s in seasons], ['gold', 'ranked', 'mention'])

    def test_best_latest_and_counts(self):
        self._rank(self.seasons[0], '4')
        self._rank(self.seasons[1], '2')
        self._rank(self.seasons[2], '2')
        self._rank(self.seasons[3], 'IM')
        _, summary = _journey_pr_history(self.p)
        self.assertEqual(summary['best']['short'], 'S3')          # tie on #2 -> the more recent season
        self.assertEqual(summary['latest']['label'], 'IM')
        self.assertEqual((summary['appearances'], summary['ranked_seasons'], summary['top3']), (4, 3, 2))
        self.assertEqual(summary['number_ones'], 0)

    def test_mention_only_player_has_no_best(self):
        self._rank(self.seasons[0], 'HM')
        _, summary = _journey_pr_history(self.p)
        self.assertIsNone(summary['best'])
        self.assertEqual(summary['ranked_seasons'], 0)

    def test_latest_is_current_only_for_the_newest_finished_michigan_season(self):
        self._rank(self.seasons[3], '3')
        self.assertTrue(_journey_pr_history(self.p)[1]['latest_is_current'])
        PRSeason.objects.create(name='S5', start_date=_dt.date(2025, 1, 1),
                                end_date=_dt.date(2025, 6, 30), region_code_id=7)
        self.assertFalse(_journey_pr_history(self.p)[1]['latest_is_current'])


class JourneyShellDeepLinkTests(TestCase):
    def test_deep_link_exposes_player_name_and_year(self):
        p = Player.objects.create(name='Link (#9, SSBM Rank 2024)')
        resp = self.client.get(f'/journey/?player={p.id}&year=2025')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['initial_player'], p.id)
        self.assertEqual(resp.context['initial_player_name'], 'Link')
        self.assertEqual(resp.context['initial_year'], 2025)
        self.assertContains(resp, f'loadJourney({p.id}, 2025)')

    def test_plain_page_and_unknown_player_do_not_autoload(self):
        self.assertNotIn('initial_player', self.client.get('/journey/').context)
        self.assertNotIn('initial_player', self.client.get('/journey/?player=999999').context)
