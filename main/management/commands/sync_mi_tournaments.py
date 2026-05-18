import time
import requests
import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
import environ
from main.models import Tournament, SyncErrorLog
from main.data_entry import enter_tournament

class Command(BaseCommand):
    help = 'Fetches recent Melee tournaments in Michigan from Start.gg and imports them into the database.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--after',
            type=str,
            help='Start date in YYYY-MM-DD format (e.g., 2025-12-20). If not provided, defaults to the date of the most recent tournament in the DB.',
        )

    def handle(self, *args, **options):
        # 1. Setup Environment and Token
        env = environ.Env()
        environ.Env.read_env()
        token = env('SMASHGG_TOKEN', default=None)
        
        if not token:
            self.stdout.write(self.style.ERROR('SMASHGG_TOKEN not found in environment variables.'))
            return

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        # 2. Determine the 'After' Date
        if options['after']:
            try:
                after_date = datetime.datetime.strptime(options['after'], '%Y-%m-%d')
                after_timestamp = int(after_date.timestamp())
                self.stdout.write(f"Using provided after date: {options['after']} ({after_timestamp})")
            except ValueError:
                self.stdout.write(self.style.ERROR('Invalid date format. Please use YYYY-MM-DD.'))
                return
        else:
            # Get the most recent tournament date from our DB
            latest_tournament = Tournament.objects.order_by('-date').first()
            if latest_tournament and latest_tournament.date:
                # Go back a couple of days from the latest to catch overlaps
                after_date = latest_tournament.date - datetime.timedelta(days=1)
                # Convert the date object to a datetime object so we can get the timestamp
                after_datetime = datetime.datetime.combine(after_date, datetime.datetime.min.time())
                after_timestamp = int(after_datetime.timestamp())
                self.stdout.write(f"Using date from latest DB tournament: {after_date.strftime('%Y-%m-%d')} ({after_timestamp})")
            else:
                # Default to a safe recent date if DB is empty (e.g. start of 2025)
                after_timestamp = 1735689600 
                self.stdout.write("Database empty. Using default start date.")

        # 3. The GraphQL Query
        query = """
        query TournamentsByState($perPage: Int!, $page: Int!, $videogameId: [ID!], $afterDate: Timestamp!, $state: String!) {
          tournaments(query: {
            perPage: $perPage
            page: $page
            sortBy: "startAt desc"
            filter: {
              videogameIds: $videogameId
              afterDate: $afterDate
              addrState: $state
            }
          }) {
            pageInfo {
              totalPages
            }
            nodes {
              id
              name
              slug
              startAt
              isOnline
              events {
                id
                name
                slug
                type
                numEntrants
                videogame {
                  id
                }
              }
            }
          }
        }
        """

        page = 1
        total_pages = 1
        tournaments_to_process = []

        self.stdout.write(self.style.SUCCESS("Fetching tournament list from Start.gg..."))

        now = datetime.datetime.now()
        cutoff_date = now - datetime.timedelta(days=1)
        cutoff_timestamp = int(cutoff_date.timestamp())
        self.stdout.write(f"Safety Cutoff: Skipping tournaments starting after {cutoff_date.strftime('%Y-%m-%d %H:%M')} ({cutoff_timestamp})")

        # 4. Fetch loop
        while page <= total_pages:
            variables = {
                "perPage": 30,
                "page": page,
                "videogameId": [1], # 1 = Super Smash Bros. Melee
                "afterDate": after_timestamp,
                "state": "MI"
            }

            response = requests.post(
                'https://api.start.gg/gql/alpha',
                json={'query': query, 'variables': variables},
                headers=headers
            )

            if response.status_code != 200:
                self.stdout.write(self.style.ERROR(f"API Error: {response.status_code} - {response.text}"))
                break

            data = response.json()
            
            if 'errors' in data:
                self.stdout.write(self.style.ERROR(f"GraphQL Error: {data['errors']}"))
                break

            tournaments_data = data['data']['tournaments']
            total_pages = tournaments_data['pageInfo']['totalPages']
            
            for t in tournaments_data['nodes']:
                tournaments_to_process.append(t)

            self.stdout.write(f"Fetched page {page}/{total_pages}...")
            page += 1
            time.sleep(1) # Be nice to the API

        self.stdout.write(f"Found {len(tournaments_to_process)} Michigan tournaments in date range.")

        # 5. Filter and Ingest Logic
        new_ingest_count = 0
        
        # Initialize memory caches to prevent N+1 database queries
        from main.models import Player, Set
        self.stdout.write("Initializing memory caches for fast ingestion...")
        player_list_cache = set(Player.objects.values_list('id', flat=True))
        set_list_cache = set(Set.objects.values_list('id', flat=True))
        
        for t in tournaments_to_process:
            # Skip tournaments that started within the last 48 hours (likely ongoing)
            if t['startAt'] > cutoff_timestamp:
                self.stdout.write(self.style.WARNING(f"Skipping '{t['name']}': Tournament is too recent/ongoing (starts at {datetime.datetime.fromtimestamp(t['startAt']).strftime('%Y-%m-%d %H:%M')})."))
                continue

            # Skip online tournaments
            if t.get('isOnline'):
                self.stdout.write(self.style.WARNING(f"Skipping '{t['name']}': Tournament is online."))
                continue

            # Look for the correct Melee Singles event inside the tournament
            potential_events = []
            for event in t.get('events', []):
                # type 1 = Singles (1v1), videogame 1 = Melee
                if event.get('type') == 1 and event.get('videogame', {}).get('id') == 1:
                    name_lower = event.get('name', '').lower()
                    
                    # Exclude common unwanted bracket types (Amateur, Side events, etc.)
                    # We use a mix of specific phrases and prefixes
                    bad_keywords = ['amateur', 'am bracket', 'am s bracket', 'side', 'item', 'redemption', 'ladder', 'crew', 'doubles', '2v2', 'secondary']
                    is_bad_bracket = any(bad in name_lower for bad in bad_keywords)
                    
                    # Extra check for "AM" at the start or with spaces
                    if not is_bad_bracket:
                        is_bad_bracket = name_lower.startswith('am ') or name_lower.startswith('ams ') or ' am ' in name_lower
                    
                    if not is_bad_bracket:
                        potential_events.append(event)
            
            if not potential_events:
                self.stdout.write(self.style.WARNING(f"Skipping '{t['name']}': No valid Melee Singles event found."))
                continue

            # Sort potential events to find the "Main" one:
            # 1. Prioritize events with "Singles" in the name
            # 2. Then prioritize higher entrant counts
            potential_events.sort(key=lambda x: ('singles' in x['name'].lower(), x.get('numEntrants', 0)), reverse=True)
            valid_event = potential_events[0]

            event_entrants = valid_event.get('numEntrants') or 0
            if event_entrants <= 4:
                self.stdout.write(self.style.WARNING(f"Skipping '{t['name']}' ({valid_event['name']}): Only {event_entrants} entrants."))
                continue

            event_id = valid_event['id']
            
            # Check if we already have this tournament in the database
            if Tournament.objects.filter(id=event_id).exists():
                self.stdout.write(f"Skipping '{t['name']}': Already in database.")
                continue

            # Construct the clean URL using the slug provided by the API
            url = f"https://start.gg/{valid_event['slug']}"
            
            self.stdout.write(self.style.SUCCESS(f"Ingesting NEW Tournament: '{t['name']}' (Event: {valid_event['name']})"))
            
            try:
                # Call the existing data entry function
                enter_tournament(url, is_pr_eligible=True, player_list_cache=player_list_cache, set_list_cache=set_list_cache)
                new_ingest_count += 1
                self.stdout.write(self.style.SUCCESS(f"Successfully added '{t['name']}'!"))
            except Exception as e:
                error_msg = f"Failed to ingest '{t['name']}': {str(e)}"
                self.stdout.write(self.style.ERROR(error_msg))
                SyncErrorLog.objects.create(
                    tournament_name=t['name'],
                    tournament_slug=t['slug'],
                    tournament_url=url,
                    error_message=str(e)
                )
            
            # Sleep to prevent hitting rate limits during heavy data fetching
            time.sleep(2)

        self.stdout.write(self.style.SUCCESS(f"Sync complete! {new_ingest_count} new tournaments added to the database."))