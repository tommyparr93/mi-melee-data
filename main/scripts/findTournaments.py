import pysmashgg
import json
import time

# insert your own
smashggToken = ""
smash = pysmashgg.SmashGG(smashggToken, True)



x = 1
tournaments_by_size = smash.custom_search(5, 1, 1628351000, int(time.time()), x)
tournaments = []

# Reading through all sets from tournament
while len(tournaments_by_size) > 0:
    x += 1
    tournaments_by_size = smash.custom_search(5, 1, 1628351000, int(time.time()), x)
    tournaments.extend(tournaments_by_size)


print(tournaments)

for t in tournaments:
    if t['eventName'] != "Melee Singles":
        tournaments.remove(t)




with open('dataclean-new.json', 'w') as f:
    json.dump(tournaments, f, indent=4)