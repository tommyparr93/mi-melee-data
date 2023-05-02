import time
import json
import psycopg2
import datetime

import pysmashgg

#smash gg token, please use your own
smashggToken = ""


smash = pysmashgg.SmashGG(smashggToken, True)

class Set:
    def __init__(self, id, tournamentKey, p1id, p2id, p1name, p2name, winner, p1score, p2score, location, bestof, playedBool):
        self.id = id;
        self.tournamentKey = tournamentKey;
        self.p1id = p1id;
        self.p2id = p2id;
        self.p1name = p1name;
        self.p2name = p2name;
        self.winner = winner;
        self.p1score = p1score;
        self.p2score = p2score;
        self.location = location;
        self.bestof = bestof;
        self.playedBool = playedBool;


# CREATING DATABASE CONNECTION AND FINDING ALL PLAYERS TO CHECK AGAINST
print("Connecting to DB")
conn = psycopg2.connect("GRAB FROM ENV")
# print(results)

# create a cursor for  postgres database
cur = conn.cursor()

# Find and create list of current players in DB
print("Finding all players from database")
cur.execute("SELECT * FROM player;")
player_query = cur.fetchall()
player_list = []
for player in player_query:
    player_list.append(player[0])

# Find and create list of current players in DB
print("Finding all tournaments from database")
cur.execute("SELECT * FROM tournament;")
t_query = cur.fetchall()
t_list = []
for t in t_query:
    t_list.append(t[0])

print("Finding all tournaments results from database")
cur.execute("SELECT tour_id, playerid FROM tournament_results;")
t_results_query = cur.fetchall()


# Find and create list of sets in DB
print("Finding all sets from database")
cur.execute("SELECT * FROM set;")
s_query = cur.fetchall()
s_list = []
for s in s_query:
    s_list.append(s[0])

# GETTING TOURNAMENT / EVENT INFO FOR THIS EVENT NAME
f = open('dataclean-new.json')
data = json.load(f)
for i in data:
    print(i['tournamentSlug'])
    t_input = (i['tournamentSlug'])

    tournament = smash.tournament_show(t_input)
    print(tournament)
    t_name = tournament['name']
    t_date = datetime.datetime.fromtimestamp(tournament['startTimestamp'])
    t_city = tournament['city']
    t_entrants = tournament['entrants']

    events = smash.tournament_show_events(t_input)
    # Shows the results of an event with only player name, id, and placement

    event_id = 0
    for event in events:
        print(event)
        if event['slug'] == "melee-singles" or event['slug'] == "melee-1v1-singles":
            print(event['slug'])
            event_id = event['id']

    print("Event ID: ", event_id)


    # Checking / adding tournament
    if event_id not in t_list:
        print("tournament ", t_name, " not in DB, adding tournament", t_name)
        SQL = "INSERT INTO tournament (tour_id, name, date, city, entrant_count) VALUES (%s, %s,%s, %s, %s);"  # Note: no quotes
        data = (event_id, t_name, t_date, t_city, t_entrants,)
        cur.execute(SQL, data)
        conn.commit()
        t_list.append(event_id)



    # GETTING SETS / placing them in a list
    x = 1
    getSets = smash.event_show_sets(event_id, x)
    setLength = len(getSets)
    sets = []
    while len(getSets) > 0:
        sets.extend(getSets)
        x = x + 1
        getSets = smash.event_show_sets(event_id, x)

    with open('sets.json', 'w') as f:
        json.dump(sets, f, indent=4)

    # SET PROCESSING
    for set in sets:
        readingSet = set
        p1id = (readingSet['entrant1Players'])[0]['playerId']
        p2id = (readingSet['entrant2Players'])[0]['playerId']
        set_id = readingSet['id']
        p1name = (readingSet['entrant1Players'])[0]['playerTag']
        p2name = (readingSet['entrant2Players'])[0]['playerTag']
        p1score = readingSet['entrant1Score']
        p2score = readingSet['entrant2Score']
        winner = int
        tournamentid = event_id
        location = readingSet['fullRoundText']
        bestOf = int
        if p1score > p2score:
            winner = p1id
            if p1score == 2:
                bestOf = 3
            if p1score == 3:
                bestOf = 5
        else:
            winner = p2id
            if p2score == 2:
                bestOf = 3
            if p2score == 3:
                bestOf = 5
        if (p1score + p2score) >= 0:
            playedBool = True
        else:
            playedBool = False
        print(set)
        # print(p1id, p2id, p1name, p2name, set_id, p1score, p2score, winner, bestOf, location, tournamentid, playedBool,
        #      sep='-')

        # FINAL SET FORMAT
        transformedSet = Set(set_id, tournamentid, p1id, p2id, p1name, p2name, winner, p1score, p2score, location,
                                  bestOf, playedBool)

        # PROCESS SETS TO DATABASE

        # Check Player vs DB, add if not found
        if p1id not in player_list:
            print("Player ", p1name, " not in DB, adding player", p1name)
            SQL = "INSERT INTO player (playerid, name) VALUES (%s, %s);"  #
            data = (p1id, p1name)
            cur.execute(SQL, data)
            player_list.append(p1id)
            conn.commit()

        if p2id not in player_list:
            print("Player ", p2name, " not in DB, adding player", p2name)
            SQL = "INSERT INTO player (playerid, name) VALUES (%s, %s);"
            data = (p2id, p2name)
            cur.execute(SQL, data)
            player_list.append(p2id)
            conn.commit()

        # now that players / tournament are in DB, attempt to add set
        if set_id not in s_list:
            print("Set is not in DB")
            SQL = "INSERT INTO set (id, player1, player2, player1score, player2score, winnerid, tour_id, " \
                  " location, played) " \
                  "VALUES " \
                  "(%s, %s,%s, %s, %s, %s, %s, %s, %s);"
            data = (set_id, p1id, p2id, p1score, p2score, winner, event_id, location, playedBool)
            cur.execute(SQL, data)
            conn.commit()
            s_list.append(set_id)


    #Checking Tournament Results
    ## GETTING RESULT INFO
    results = smash.tournament_show_lightweight_results(t_input, 'melee-singles', 1)
    print(results)
    for result in results:
        p_result_id = result['playerid']
        placement = result['placement']
        pair = (event_id, p_result_id)
        t_results_query.extend(pair)
        if pair not in t_results_query:
            SQL = "INSERT INTO tournament_results (tour_id, playerid, placement) VALUES (%s, %s, %s);"  # Note: no quotes
            data = (event_id, p_result_id, placement)
            cur.execute(SQL, data)
            conn.commit()
    time.sleep(25)

conn.commit
conn.close()
print('Database connection closed.')
