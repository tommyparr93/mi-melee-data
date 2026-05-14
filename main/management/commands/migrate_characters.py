import os
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from main.models import Player, Character

# Map of standard Melee character names to their schmoigo github slugs
MELEE_CHARACTERS = {
    "Fox": "fox",
    "Falco": "falco",
    "Marth": "marth",
    "Sheik": "sheik",
    "Jigglypuff": "jigglypuff",
    "Peach": "peach",
    "Captain Falcon": "captain_falcon",
    "Ice Climbers": "ice_climbers",
    "Pikachu": "pikachu",
    "Yoshi": "yoshi",
    "Samus": "samus",
    "Luigi": "luigi",
    "Mario": "mario",
    "Dr. Mario": "dr_mario",
    "Ganondorf": "ganondorf",
    "Link": "link",
    "Donkey Kong": "donkey_kong",
    "Young Link": "young_link",
    "Pichu": "pichu",
    "Zelda": "zelda",
    "Roy": "roy",
    "Mewtwo": "mewtwo",
    "Mr. Game & Watch": "mr_game_and_watch",
    "Ness": "ness",
    "Bowser": "bowser",
    "Kirby": "kirby",
}

class Command(BaseCommand):
    help = 'Creates Character models and migrates string data to ForeignKeys.'

    def handle(self, *args, **options):
        # 1. Ensure the icon directory exists
        icon_dir = os.path.join(settings.BASE_DIR, 'static', 'images', 'characters')
        if not os.path.exists(icon_dir):
            os.makedirs(icon_dir)

        # 2. Create the Character records
        self.stdout.write("Setting up Character models...")
        
        for char_name, slug in MELEE_CHARACTERS.items():
            character, created = Character.objects.get_or_create(name=char_name)
            
            local_filename = f"{slug}.png"
            static_url_path = f"/static/images/characters/{local_filename}"
            
            if character.icon_path != static_url_path:
                character.icon_path = static_url_path
                character.save()

        # 3. Migrate the string fields on the Player model to the new ForeignKeys
        self.stdout.write("Migrating string character data to relational keys...")
        players = Player.objects.all()
        updated_count = 0
        
        char_map = {c.name.lower(): c for c in Character.objects.all()}
        char_map["falcon"] = char_map["captain falcon"]
        char_map["puff"] = char_map["jigglypuff"]
        char_map["doc"] = char_map["dr. mario"]
        char_map["g&w"] = char_map["mr. game & watch"]
        char_map["dk"] = char_map["donkey kong"]

        for player in players:
            needs_save = False
            
            if player.character_main and not player.main_char:
                match = char_map.get(player.character_main.lower().strip())
                if match:
                    player.main_char = match
                    needs_save = True
                    
            if player.character_alt and not player.secondary_char:
                match = char_map.get(player.character_alt.lower().strip())
                if match:
                    player.secondary_char = match
                    needs_save = True
                    
            if needs_save:
                player.save()
                updated_count += 1
                
        self.stdout.write(self.style.SUCCESS(f"Migration complete! Updated {updated_count} players."))
        self.stdout.write(self.style.WARNING(
            "\n*** ACTION REQUIRED FOR ICONS ***\n"
            "The database is ready, but you need to manually add the PNG files.\n"
            f"1. Go to: https://ssbwiki.com/Category:Head_icons_(SSBM)\n"
            f"2. Download the default icons for each character.\n"
            f"3. Rename them to match the character names (e.g., 'fox.png', 'captain_falcon.png').\n"
            f"4. Place them in this folder: {icon_dir}\n"
        ))
