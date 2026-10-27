import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from main.models import Tournament

# The only columns this command is allowed to write. Everything else on a
# tournament (name, date, entrants, region...) is left exactly as it is, so it
# is safe to run against a database whose other data has moved on.
GEO_FIELDS = ['lat', 'lng', 'venue_name', 'venue_address', 'postal_code']
FILL_ONLY_FIELDS = ['city', 'state']
MAX_LEN = {'venue_name': 255, 'venue_address': 500, 'postal_code': 20}


class Command(BaseCommand):
    help = ("Apply geocoded location columns from a CSV (id, lat, lng, venue_name, "
            "venue_address, postal_code, city, state) to matching tournaments by id.")

    def add_arguments(self, parser):
        parser.add_argument('csv_path', help='CSV exported from a geocoded database')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change without writing anything')
        parser.add_argument('--force', action='store_true',
                            help='Overwrite coordinates that are already set '
                                 '(default: only tournaments with no lat/lng)')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']

        try:
            fh = open(options['csv_path'], newline='', encoding='utf-8')
        except OSError as e:
            raise CommandError(f"Cannot read {options['csv_path']}: {e}")

        rows, bad = {}, 0
        with fh:
            for r in csv.DictReader(fh):
                try:
                    rows[int(r['id'])] = {
                        'lat': float(r['lat']), 'lng': float(r['lng']), 'raw': r,
                    }
                except (KeyError, TypeError, ValueError):
                    bad += 1

        existing = Tournament.objects.in_bulk(list(rows))
        updated, skipped_has_coords, missing = [], 0, 0
        for tid, row in rows.items():
            t = existing.get(tid)
            if t is None:
                missing += 1
                continue
            if t.lat is not None and t.lng is not None and not force:
                skipped_has_coords += 1
                continue

            t.lat, t.lng = row['lat'], row['lng']
            for f in ('venue_name', 'venue_address', 'postal_code'):
                val = (row['raw'].get(f) or '').strip()
                if val:
                    setattr(t, f, val[:MAX_LEN[f]])
            for f in FILL_ONLY_FIELDS:           # never replace an existing value
                val = (row['raw'].get(f) or '').strip()
                if val and not getattr(t, f):
                    setattr(t, f, val)
            updated.append(t)

        if updated and not dry_run:
            with transaction.atomic():
                Tournament.objects.bulk_update(
                    updated, GEO_FIELDS + FILL_ONLY_FIELDS, batch_size=500)

        verb = 'Would update' if dry_run else 'Updated'
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {len(updated)} tournaments | already had coordinates: "
            f"{skipped_has_coords} | id not in this database: {missing} | "
            f"bad CSV rows: {bad}"))
