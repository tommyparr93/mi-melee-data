import time
from django.core.management.base import BaseCommand
from main.models import Tournament


# Hardcoded fallback coordinates for known Michigan cities. Saves API calls
# and avoids ambiguity for very common cities (Lansing, MI vs Lansing, IL etc.)
MI_CITY_COORDS = {
    'ann arbor': (42.2808, -83.7430),
    'detroit': (42.3314, -83.0458),
    'lansing': (42.7325, -84.5555),
    'east lansing': (42.7370, -84.4839),
    'grand rapids': (42.9634, -85.6681),
    'kalamazoo': (42.2917, -85.5872),
    'flint': (43.0125, -83.6875),
    'ypsilanti': (42.2411, -83.6130),
    'troy': (42.6064, -83.1498),
    'novi': (42.4806, -83.4755),
    'royal oak': (42.4895, -83.1446),
    'sterling heights': (42.5803, -83.0302),
    'farmington hills': (42.4989, -83.3677),
    'pontiac': (42.6389, -83.2910),
    'dearborn': (42.3223, -83.1763),
    'warren': (42.5145, -83.0147),
    'livonia': (42.3684, -83.3527),
    'westland': (42.3242, -83.4002),
    'rochester hills': (42.6584, -83.1499),
    'auburn hills': (42.6875, -83.2341),
    'birmingham': (42.5467, -83.2113),
    'taylor': (42.2407, -83.2696),
    'wyandotte': (42.2142, -83.1496),
    'midland': (43.6156, -84.2472),
    'saginaw': (43.4195, -83.9508),
    'bay city': (43.5944, -83.8889),
    'battle creek': (42.3211, -85.1797),
    'jackson': (42.2459, -84.4013),
    'mount pleasant': (43.5978, -84.7675),
    'holland': (42.7875, -86.1089),
    'muskegon': (43.2342, -86.2484),
    'traverse city': (44.7631, -85.6206),
    'marquette': (46.5436, -87.3955),
    'houghton': (47.1219, -88.5694),
    'sault ste. marie': (46.4953, -84.3453),
    'allendale': (42.9725, -85.9461),
}


class Command(BaseCommand):
    help = 'Geocode tournaments that are missing lat/lng using city + state.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Re-geocode tournaments that already have coordinates')
        parser.add_argument('--limit', type=int, default=None, help='Limit number of tournaments to process')

    def handle(self, *args, **options):
        force = options['force']
        limit = options['limit']

        qs = Tournament.objects.exclude(online=True).exclude(city__isnull=True).exclude(city='')
        if not force:
            qs = qs.filter(lat__isnull=True)

        if limit:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(f"Found {total} tournaments to geocode")

        if total == 0:
            return

        # Phase 1: hardcoded MI city lookup (instant, no API calls)
        local_hits = 0
        remaining = []
        for t in qs:
            city_lower = (t.city or '').strip().lower()
            coords = MI_CITY_COORDS.get(city_lower)
            if coords:
                t.lat, t.lng = coords
                t.save(update_fields=['lat', 'lng'])
                local_hits += 1
            else:
                remaining.append(t)

        self.stdout.write(self.style.SUCCESS(f"Resolved {local_hits} via hardcoded MI city lookup"))

        if not remaining:
            return

        # Phase 2: Nominatim API for the rest (slow, rate limited)
        try:
            from geopy.geocoders import Nominatim
            from geopy.exc import GeocoderTimedOut, GeocoderServiceError
        except ImportError:
            self.stdout.write(self.style.ERROR(
                "geopy not installed. Run: pip install geopy\n"
                f"Skipping {len(remaining)} tournaments that need API geocoding."
            ))
            return

        geolocator = Nominatim(user_agent='mi_melee_stats')
        api_hits = 0
        api_misses = 0

        for t in remaining:
            parts = [t.city]
            if t.state:
                parts.append(t.state)
            parts.append('USA')
            query = ', '.join(parts)

            try:
                location = geolocator.geocode(query, timeout=10)
                if location:
                    t.lat = location.latitude
                    t.lng = location.longitude
                    t.save(update_fields=['lat', 'lng'])
                    api_hits += 1
                    safe_name = t.name[:50].encode('ascii', errors='replace').decode('ascii')
                    self.stdout.write(f"  [OK] {safe_name:<50} -> {query}")
                else:
                    api_misses += 1
                    safe_name = t.name[:50].encode('ascii', errors='replace').decode('ascii')
                    self.stdout.write(self.style.WARNING(f"  [SKIP] {safe_name:<50} -> {query} (not found)"))
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                api_misses += 1
                safe_name = t.name[:50].encode('ascii', errors='replace').decode('ascii')
                self.stdout.write(self.style.WARNING(f"  [SKIP] {safe_name:<50} -> {query} ({e})"))

            time.sleep(1.1)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Local: {local_hits}, API hits: {api_hits}, misses: {api_misses}"
        ))
