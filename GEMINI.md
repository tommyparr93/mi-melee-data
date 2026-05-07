# Melee PR Tracker - Gemini Instructions

This project is a Django-based application for tracking Super Smash Bros. Melee tournament results, head-to-head statistics, and managing Power Rankings (PR) seasons.

## Core Tech Stack
- **Backend:** Django 4.2 (Python)
- **Database:** PostgreSQL (via `psycopg2`)
- **Frontend:** Django Templates with Bootstrap v5 (`django-bootstrap-v5`)
- **Data Fetching:** `pysmashgg` for Start.gg integration
- **Configuration:** `django-environ` for environment variables

## Project Structure & Conventions

### Models and Database
- **Unmanaged Models:** Several models use `managed = False` because they map to a pre-existing database schema or use composite keys that Django doesn't natively support (e.g., `TournamentResults`). **Do not change these without careful review.**
- **Player Aliases:** Use the `main_account` field in the `Player` model to link secondary accounts/tags to a primary player profile.
- **PR Eligibility:** The `pr_eligible` flag on `Set` and `Player` determines if they are counted toward Power Rankings calculations.

### Views and Templates
- **Coding Style:** A mix of Function-Based Views (FBVs) and Class-Based Views (CBVs) is used. Prefer CBVs for standard CRUD and FBVs for complex data processing.
- **Calculations:** Complex head-to-head or PR calculations are often performed in-memory in views. Consider refactoring repeated logic into model methods or managers.
- **UI:** Follow Bootstrap v5 patterns. Templates are located in `main/templates/`.

### Scripts
- Utility scripts for data entry and cleaning are located in `main/scripts/`. Use `python manage.py runscript <script_name>` if using `django-extensions`, or execute them directly if they are standalone.

## Common Workflows

### Database Migrations
Always run `python manage.py makemigrations` and `python manage.py migrate` after model changes. Be extremely cautious when migrating unmanaged models.

### Data Entry
Tournament data is often pulled via scripts. See `main/data_entry.py` and `main/scripts/getTournamentData.py`.

### Environment Setup
Ensure a `.env` file exists in the root directory with the following (at minimum):
- `DEBUG`
- `SECRET_KEY`
- `DATABASE_URL` (PostgreSQL format)

## Gemini-Specific Rules
- **Surgical Edits:** When modifying views, maintain the existing indentation and naming conventions.
- **Test Before Commit:** Always verify changes by running the development server and checking the affected pages.
- **Documentation:** Update this `GEMINI.md` if you introduce new core architectural patterns.
