"""Core logic tests.

Focus: the pure stats math (win/loss/rate, head-to-head), the query-param
parser used across analytics, and the caching freshness contract (the
highest-risk Tier-1 change — a stale cache would be a correctness bug, so
its data-version invalidation is locked down here).
"""
from django.test import TestCase, SimpleTestCase, RequestFactory
from django.core.cache import cache
from django.http import HttpResponse

from main.models import Player, Tournament, Set, PRSeason
from main.views import (
    player_detail_calculations,
    get_head_to_head_results,
    _parse_int_param,
    _data_version,
    cached_partial,
)


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
