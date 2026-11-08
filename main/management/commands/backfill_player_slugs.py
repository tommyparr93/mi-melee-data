import time

import environ
from django.core.management.base import BaseCommand
from django.db.models import Q

from main.data_entry import fetch_player_slugs
from main.models import Player

BATCH_SIZE = 50
MAX_ATTEMPTS = 4


class Command(BaseCommand):
    help = "Fill missing start.gg profile slugs for players. Existing slugs are never changed."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report changes without saving')
        parser.add_argument('--limit', type=int, default=None, help='Process at most this many players')
        parser.add_argument('--delay', type=float, default=0.85, help='Seconds between requests')

    def handle(self, *args, **options):
        env = environ.Env()
        environ.Env.read_env()
        token = env('SMASHGG_TOKEN')

        # id > 0 excludes legacy manual entries with no start.gg player.
        queryset = Player.objects.filter(Q(startgg_slug__isnull=True) | Q(startgg_slug=''), id__gt=0).order_by('id')
        if options['limit']:
            queryset = queryset[:options['limit']]
        player_ids = list(queryset.values_list('id', flat=True))

        filled = no_profile = failed = 0
        for start in range(0, len(player_ids), BATCH_SIZE):
            batch = player_ids[start:start + BATCH_SIZE]
            slugs = self._fetch(token, batch)
            if slugs is None:
                failed += len(batch)
                continue

            no_profile += len(batch) - len(slugs)
            filled += len(slugs)
            if not options['dry_run']:
                Player.objects.bulk_update(
                    [Player(id=player_id, startgg_slug=slug) for player_id, slug in slugs.items()],
                    ['startgg_slug'],
                )
            time.sleep(options['delay'])
            if (start // BATCH_SIZE) % 20 == 0:
                self.stdout.write(f"  {min(start + BATCH_SIZE, len(player_ids))}/{len(player_ids)} checked")

        prefix = 'Dry run: would have ' if options['dry_run'] else ''
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}filled {filled} player slugs. No start.gg profile: {no_profile}. "
            f"Failed requests: {failed} players."))

    def _fetch(self, token, batch):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            slugs = fetch_player_slugs(token, batch)
            if slugs is not None:
                return slugs
            if attempt < MAX_ATTEMPTS:
                time.sleep(60 if attempt == MAX_ATTEMPTS - 1 else 2 ** attempt)
        self.stdout.write(self.style.WARNING(f"  Batch of {len(batch)} failed after {MAX_ATTEMPTS} attempts"))
        return None
