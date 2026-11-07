from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, connections

SQL_DIR = Path(__file__).resolve().parents[2] / 'agent' / 'sql'


class Command(BaseCommand):
    help = ('Create/refresh the read-only `agent` views the Ask Tom SQL tool queries, then check '
            'that the agent role really is read-only. Run as the app user after create_agent_role.sql.')

    def handle(self, *args, **options):
        sql = (SQL_DIR / 'agent_views.sql').read_text(encoding='utf-8')
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = 'mimelee_agent'")
            if not cursor.fetchone():
                raise CommandError('Role mimelee_agent does not exist yet; run create_agent_role.sql as postgres first.')
            cursor.execute(sql)
        self.stdout.write(self.style.SUCCESS(f'agent views created in {connection.settings_dict["NAME"]}'))

        if 'agent' not in settings.DATABASES:
            self.stdout.write(self.style.WARNING('AGENT_DB_USER is not set, so the role checks were skipped.'))
            return
        self._verify()

    def _verify(self):
        """Prove the guarantees from the agent's own connection."""
        failures = []
        checks = [
            ('can read agent views', 'SELECT count(*) FROM agent.players', True),
            ('cannot read raw tables', 'SELECT count(*) FROM public.player', False),
            ('cannot read users', 'SELECT count(*) FROM public.auth_user', False),
            ('cannot write', "UPDATE public.player SET name = name WHERE false", False),
            ('cannot create tables', 'CREATE TABLE public.agent_probe (x int)', False),
            ('cannot create temp tables', 'CREATE TEMP TABLE agent_probe (x int)', False),
            ('cannot leave read-only mode', "SET default_transaction_read_only = off; CREATE TABLE agent.p (x int)", False),
            ('long queries are cancelled', 'SELECT pg_sleep(8)', False),
        ]
        conn = connections['agent']
        for label, query, should_succeed in checks:
            ok = True
            try:
                with conn.cursor() as cursor:
                    cursor.execute(query)
            except Exception:
                ok = False
            finally:
                conn.rollback() if not conn.get_autocommit() else None
            passed = ok == should_succeed
            self.stdout.write(f"  [{'PASS' if passed else 'FAIL'}] {label}")
            if not passed:
                failures.append(label)
        conn.close()
        if failures:
            raise CommandError(f'agent role is NOT locked down: {", ".join(failures)}')
        self.stdout.write(self.style.SUCCESS('agent role verified read-only'))
