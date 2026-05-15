import time

import environ
import requests
from django.core.management.base import BaseCommand

from main.models import Tournament

STARTGG_ENDPOINT = 'https://api.start.gg/gql/alpha'

# Tournament.id is the Start.gg *event* id (set during import in data_entry.py),
# so we query by event id — this covers every imported tournament, not just the
# few that happen to have a slug stored. Start.gg's venue lat/lng is the pin the
# tournament organiser set, far more accurate than geocoding a city name.
LOCATION_QUERY = """
query EventLocation($eventId: ID!) {
  event(id: $eventId) {
    tournament {
      name
      lat
      lng
      venueName
      venueAddress
      postalCode
      addrState
      city
    }
  }
}
"""


class Command(BaseCommand):
    help = "Pull authoritative venue coordinates for tournaments directly from the Start.gg API."

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='Re-fetch tournaments that already have lat/lng')
        parser.add_argument('--limit', type=int, default=None,
                            help='Limit number of tournaments to process (for testing)')
        parser.add_argument('--delay', type=float, default=0.85,
                            help='Seconds between API requests (default 0.85 = ~70 req/min, '
                                 'safely under Start.gg 80 req/60s limit)')

    def handle(self, *args, **options):
        force = options['force']
        limit = options['limit']
        delay = options['delay']

        env = environ.Env()
        environ.Env.read_env()
        token = env('SMASHGG_TOKEN')

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }

        # id > 0 excludes the handful of legacy manual entries with no Start.gg event
        qs = Tournament.objects.filter(id__gt=0).exclude(online=True)
        if not force:
            qs = qs.filter(lat__isnull=True)
        qs = qs.order_by('-date')
        if limit:
            qs = qs[:limit]

        tournaments = list(qs)
        total = len(tournaments)
        self.stdout.write(f"Fetching Start.gg locations for {total} tournaments "
                          f"(delay {delay}s/request, ~{int(60/delay)} req/min, "
                          f"~{int(total * delay / 60) + 1} min total)")

        if total == 0:
            return

        hits = 0
        no_coords = 0
        errors = 0

        for i, t in enumerate(tournaments, 1):
            try:
                resp = requests.post(
                    STARTGG_ENDPOINT,
                    json={'query': LOCATION_QUERY, 'variables': {'eventId': t.id}},
                    headers=headers,
                    timeout=20,
                )
            except requests.RequestException as e:
                errors += 1
                self.stdout.write(self.style.WARNING(f"  [ERR]  {self._safe(t.name)} -> request failed ({e})"))
                time.sleep(delay)
                continue

            # Start.gg returns 429 if rate limited — back off hard then retry
            if resp.status_code == 429:
                self.stdout.write(self.style.WARNING("  Rate limited (429). Backing off 60s..."))
                time.sleep(60)
                continue

            if resp.status_code != 200:
                errors += 1
                self.stdout.write(self.style.WARNING(
                    f"  [ERR]  {self._safe(t.name)} -> HTTP {resp.status_code}"))
                time.sleep(delay)
                continue

            payload = resp.json()
            event = (payload.get('data') or {}).get('event')
            data = event.get('tournament') if event else None

            if not data:
                errors += 1
                self.stdout.write(self.style.WARNING(
                    f"  [MISS] {self._safe(t.name)} -> event {t.id} not found on Start.gg"))
                time.sleep(delay)
                continue

            lat = data.get('lat')
            lng = data.get('lng')
            update_fields = []

            if data.get('addrState'):
                t.state = data['addrState']
                update_fields.append('state')
            if data.get('city'):
                t.city = data['city']
                update_fields.append('city')
            if data.get('venueName'):
                t.venue_name = data['venueName'][:255]
                update_fields.append('venue_name')
            if data.get('venueAddress'):
                t.venue_address = data['venueAddress'][:500]
                update_fields.append('venue_address')
            if data.get('postalCode'):
                t.postal_code = str(data['postalCode'])[:20]
                update_fields.append('postal_code')

            if lat is not None and lng is not None:
                t.lat = lat
                t.lng = lng
                update_fields += ['lat', 'lng']
                hits += 1
                status = f"[OK]   ({lat:.4f}, {lng:.4f})"
            else:
                no_coords += 1
                status = "[NOCO] no venue pin"

            if update_fields:
                t.save(update_fields=update_fields)

            self.stdout.write(f"  {status:<26} {self._safe(t.name)}")
            if i % 50 == 0 or i == total:
                self.stdout.write(f"  ---- {i}/{total} processed ----")

            time.sleep(delay)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Coordinates set: {hits}, no Start.gg pin: {no_coords}, errors: {errors}"))
        if no_coords:
            self.stdout.write(
                "Tournaments with no Start.gg pin still need the geocode_tournaments "
                "fallback. Run: python manage.py geocode_tournaments")

    @staticmethod
    def _safe(name):
        if not name:
            return '(unnamed)'
        return name[:55].encode('ascii', errors='replace').decode('ascii')
