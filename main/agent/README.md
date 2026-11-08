# Ask Tom

A chat page at `/ask-tom/` that answers questions about the site's Michigan Melee data. It runs locally for now and is not deployed. Only superusers can see the page or nav link, or use the bot.

## Setup

```bash
pip install -r requirements-agent.txt
python manage.py migrate main
```

The chat needs the `mimelee_agent` read-only database role for its SQL tool. `sql/create_agent_role.sql` creates it, and `python manage.py setup_agent_db` builds the views and checks the lockdown. Without the role, `run_sql` and `get_schema` are simply hidden from the model.

Add your key to `.env.sandbox`, then run the site:

```
ANTHROPIC_API_KEY=sk-ant-...
```

```bash
python manage.py runserver 8001
python manage.py ask_agent "Who won Tipped Off 16?" --verbose
```

On your Claude Console billing page, keep the prepaid balance and leave auto-reload off. That is the one limit the code cannot enforce or get wrong.

## Settings

Every limit is an environment variable, set low by default.

| Variable | Default | What it does |
|---|---|---|
| `ASK_TOM_ENABLED` | same as `DEBUG` | Kill switch. `false` makes the page and endpoint refuse with no API call. |
| `AGENT_BACKEND` | `claude` | `claude` or `local` (Ollama). |
| `AGENT_CLAUDE_MODEL` | `claude-haiku-5-5` | Must be listed in `pricing.py`. |
| `AGENT_CLAUDE_EFFORT` | `low` | How hard the model thinks. Higher costs more. |
| `ASK_TOM_DAILY_BUDGET_USD` | `0.50` | Global daily spend, reset at midnight UTC. |
| `ASK_TOM_RATE_PER_MINUTE` | `5` | Per IP and per session. |
| `ASK_TOM_MESSAGES_PER_DAY` | `50` | Per IP and per session, over a rolling 24 hours. |
| `ASK_TOM_TURNS_PER_CONVERSATION` | `12` | Then the visitor starts a new chat. |
| `ASK_TOM_MAX_INPUT_CHARS` | `500` | Longest question. |
| `ASK_TOM_HISTORY_MESSAGES` | `6` | Earlier messages sent to the model. |
| `AGENT_MAX_TOKENS` | `1024` | Output cap per model call. |
| `AGENT_MAX_STEPS` | `6` | Model calls per question. |
| `AGENT_MAX_TOOL_ROWS` | `50` | Rows per tool result. |
| `ASK_TOM_CLIENT_IP_HEADER` | blank | Behind nginx only, for example `HTTP_X_REAL_IP`. |
| `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_THINK`, `OLLAMA_NUM_CTX` | | Used only by the `local` backend. |

## Turning it off and checking spend

Set `ASK_TOM_ENABLED=false` and restart. For spending, run:

```bash
python manage.py agent_budget
```

If the account runs out of credit, the bot stops calling the API for the rest of the UTC day. After topping up, run `python manage.py agent_budget --clear-credit-flag`.

Every question is stored in `agent_turn` with its tools, tokens, cost and outcome. IPs and sessions are hashed. Questions are stored in full, so clear that table on whatever schedule suits you.

Each answer has a **Report this answer** button with an optional note. Reports are saved on that answer's `agent_turn` row. To review them, open Agent turns in Django admin and filter on Reported at. They make good new eval questions.

## Running the eval

```bash
python manage.py eval_agent --check-references
python manage.py eval_agent --model claude-haiku-5-5 --model claude-sonnet-5-5 --report main/agent/EVAL_RESULTS.md --log eval.jsonl
```

`--check-references` is free. A real run stops at `--max-spend` (default $1.50), and it does not count against the daily chat budget. Any model name that doesn't start with `claude-` goes to Ollama.

## Why it's built this way

**One loop you can read.** `claude.py` is a plain loop: call the model, run the tools it asked for, repeat until it answers. Owning the loop is what makes the cost controls possible, because every model call passes through one place. The Agent SDK is built for coding agents and starts a CLI process per query, which is more machinery than a read-only chat needs.

**Tools shaped like the site's features.** A tool like `get_head_to_head` encodes the definitions that are easy to get wrong, such as what counts as a set and which sets are PR-eligible. Each one returns compact JSON the model can quote directly. `run_sql` is the escape hatch for questions no tool anticipates, and the system prompt tells the model to prefer the others. Tool descriptions are effectively prompts, so they say when to use a tool as well as what it does.

**Guardrails in code, not in the prompt.** A prompt is a request, and prompt injection can talk a model out of it. So the things that must never happen are made impossible somewhere else:

- The database role can only read the `agent` views, which leave out accounts and passwords, and it times out after 5 seconds.
- `sql_guard.py` allows only SELECTs on those views using allowlisted functions. It's the fast, friendly layer, and the role is the real guarantee.
- The chat page only renders links to stats pages, so injected text can't send a visitor elsewhere.
- Conversation history comes from the server's log, so a visitor can't forge earlier assistant messages.

The prompt still says user text and database text are untrusted, but the design assumes that sometimes fails. The worst outcome of a successful injection is a wrong sentence in one reply.

**Grounding.** "Never invent stats" is enforced by giving the model the data and telling it to look things up, then tested by the eval's no-data cases. A prompt alone cannot guarantee it, which is why the page says answers can be wrong.

**Links are added by code.** The model linked some names and missed others, and asking it more firmly wouldn't make that reliable. Tool results already pair each name with its id, so `links.py` adds the links afterwards. If a job is mechanical and the data is on hand, do it in code and save the model for judgment.

**Budget holds before spending.** A check that only compares the total so far lets ten simultaneous requests all pass and overshoot together. So each model call first holds its worst-case cost inside a database lock, and swaps that for the real cost afterwards. It's in the database because the site runs several server processes, which wouldn't share memory.

**Prompt caching.** The tools and system prompt are the same on every request, so they sit before a cache breakpoint and cost a tenth of the normal input price or less when reused. The date changes daily, so it goes after the breakpoint. Anything that varies inside the cached part quietly turns caching off, so check that `cache_read_tokens` in the log is above zero. A second, moving breakpoint covers the tool results within one question, since a single answer often takes several model calls.

**Evals decide, not impressions.** The eval compares answers with live SQL results, so it stays correct as data changes. It's deliberately lenient on wording and strict on facts. It also scores what the bot should refuse. Run it before and after changing a prompt or tool, because a change that fixes one question often breaks another.

## Local models

`AGENT_BACKEND=local` uses the same tools and prompt through Ollama at no cost. In earlier testing, `qwen3:14b` was accurate but took 27 to 87 seconds, and `qwen3:8b` guessed ids. The prompt is now written for Claude and hasn't been re-tuned for these models.

## Before deploying

- Create the role and views on the production database, with a backup first.
- Set `ASK_TOM_ENABLED=true`, `ASK_TOM_CLIENT_IP_HEADER`, and have nginx set that header.
- Gunicorn needs threaded workers for streaming, because sync workers would be tied up for a whole answer.
