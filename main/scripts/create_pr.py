import environ
import psycopg2
import csv


# Pr season id
pr_season_id = 4


env = environ.Env()
environ.Env.read_env()

dbName = env("DB_NAME")
dbUser = env("DB_USER")
dbPassword = env("DB_PASSWORD")
dbHost = env("DB_HOST")
dbPort = env("DB_PORT")

print("Connecting to DB")
conn = psycopg2.connect(dbname=dbName, user=dbUser, password=dbPassword, host=dbHost, port=dbPort)
cur = conn.cursor()

with open('2021 General.csv', 'r') as pr_csv:
    reader = csv.reader(pr_csv)

    # Skip first line of csv
    next(reader)

    for line in reader:
        sql_query = 'INSERT INTO pr_season_results (rank, player_id, pr_season_id) VALUES (%s, %s, %s);'
        query_parameters = (line[0], line[2], pr_season_id)
        cur.execute(sql_query, query_parameters)
        conn.commit()

conn.close()
