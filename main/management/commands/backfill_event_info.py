import time

import environ
import requests
from django.core.management.base import BaseCommand

from main.models import Tournament

STARTGG_ENDPOINT = 'https://api.start.gg/gql/alpha'
BATCH_SIZE = 50
MAX_ATTEMPTS = 4


def build_query(event_ids):
    # Tournament.id is the start.gg event id. Aliases fetch a whole batch in one request.
    fields = '{ numEntrants tournament { slug } }'
    return 'query { ' + ' '.join(f'e{int(event_id)}: event(id: {int(event_id)}) {fields}' for event_id in event_ids) + ' }'


def clean_slug(slug):
    return slug[len('tournament/'):] if slug and slug.startswith('tournament/') else slug


class Command(BaseCommand):
    help = "Fill missing tournament slugs from start.gg. With --entrants, also correct entrant counts."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report changes without saving')
        parser.add_argument('--entrants', action='store_true',
                            help="Also set entrant_count to the event's numEntrants on start.gg")
        parser.add_argument('--limit', type=int, default=None, help='Process at most this many tournaments')
        parser.add_argument('--delay', type=float, default=0.85, help='Seconds between requests')

    def handle(self, *args, **options):
        env = environ.Env()
        environ.Env.read_env()
        self.headers = {'Authorization': f"Bearer {env('SMASHGG_TOKEN')}", 'Content-Type': 'application/json'}

        # id > 0 excludes legacy manual entries with no start.gg event.
        queryset = Tournament.objects.filter(id__gt=0).order_by('-date')
        if not options['entrants']:
            queryset = queryset.filter(slug__isnull=True) | queryset.filter(slug='')
        if options['limit']:
            queryset = queryset[:options['limit']]
        tournaments = list(queryset)

        slugs_filled = entrants_changed = not_found = failed = 0
        for start in range(0, len(tournaments), BATCH_SIZE):
            batch = tournaments[start:start + BATCH_SIZE]
            data = self._fetch(batch)
            if data is None:
                failed += len(batch)
                continue

            for tournament in batch:
                event = data.get(f'e{tournament.id}')
                slug = clean_slug(((event or {}).get('tournament') or {}).get('slug'))
                if not event:
                    not_found += 1
                    continue

                update_fields = []
                if slug and not tournament.slug:
                    tournament.slug = slug[:255]
                    update_fields.append('slug')
                    slugs_filled += 1

                entrants = event.get('numEntrants')
                if options['entrants'] and entrants and entrants != tournament.entrant_count:
                    self.stdout.write(f"  {tournament.id}: entrants {tournament.entrant_count} -> {entrants}")
                    tournament.entrant_count = entrants
                    update_fields.append('entrant_count')
                    entrants_changed += 1

                if update_fields and not options['dry_run']:
                    tournament.save(update_fields=update_fields)

            self.stdout.write(f"  {min(start + BATCH_SIZE, len(tournaments))}/{len(tournaments)} checked")
            time.sleep(options['delay'])

        prefix = 'Dry run: would have ' if options['dry_run'] else ''
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}filled {slugs_filled} slugs, changed {entrants_changed} entrant counts. "
            f"Not found on start.gg: {not_found}. Failed requests: {failed} tournaments."))

    def _fetch(self, batch):
        query = build_query(t.id for t in batch)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = requests.post(STARTGG_ENDPOINT, json={'query': query}, headers=self.headers, timeout=30)
                if response.status_code == 200:
                    data = response.json().get('data')
                    if data is not None:
                        return data
            except (requests.RequestException, ValueError):
                pass
            if attempt < MAX_ATTEMPTS:
                time.sleep(60 if attempt == MAX_ATTEMPTS - 1 else 2 ** attempt)
        self.stdout.write(self.style.WARNING(f"  Batch of {len(batch)} failed after {MAX_ATTEMPTS} attempts"))
        return None
