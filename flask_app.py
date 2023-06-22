from flask import Flask, render_template, request
from langchain.agents import create_sql_agent
from langchain.agents.agent_toolkits import SQLDatabaseToolkit
from langchain.sql_database import SQLDatabase
from langchain.chat_models import ChatOpenAI

# Load .env file
from dotenv import load_dotenv
from config_loader import ConfigLoader

app = Flask(__name__)

config_file_path = 'config.toml'
cfg = ConfigLoader(config_file_path)
cfg.load_config()

openai_api_key = cfg.get_value('openai', 'OPENAI_API_KEY')
db_user = cfg.get_value('database', 'db_user')
db_password = cfg.get_value('database', 'db_password')
db_host = cfg.get_value('database', 'db_host')
db_name = cfg.get_value('database', 'db_name')
db = SQLDatabase.from_uri(f"mysql+pymysql://{db_user}:{db_password}@{db_host}/{db_name}")


@app.route('/')
def search_form():
    return render_template('search_form.html')


@app.route('/search')
def search():
    try:
        query = request.args.get('query')
        llm = ChatOpenAI(model_name="gpt-4", openai_api_key=openai_api_key)
        toolkit = SQLDatabaseToolkit(db=db, llm=llm)

        agent_executor = create_sql_agent(
            llm=llm,
            toolkit=toolkit,
            verbose=True
        )
        results = agent_executor.run(query)
    except Exception as e:
        results = e
    return render_template('search_results.html', results=results)


if __name__ == '__main__':
    load_dotenv()
    app.run()