import json
import re
import time
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from main.agent import AgentError, get_agent
from main.agent.eval_cases import CASES


def _norm(text):
    return re.sub(r'\s+', ' ', str(text)).strip().lower()


def _short(name):
    """'Zain (#1, SSBMRank 2025)' -> 'zain': answers usually drop the ranking suffix."""
    return _norm(re.sub(r'\s*\(.*\)\s*$', '', str(name)))


def _numbers(text):
    return [Decimal(n.replace(',', '')) for n in re.findall(r'-?\d[\d,]*(?:\.\d+)?', text)]


def _has_name(answer, name):
    short = _short(name)
    return bool(short) and re.search(r'(?<![\w])' + re.escape(short) + r'(?![\w])', _norm(answer)) is not None


def _has_number(answer, value, tol=0):
    value = Decimal(str(value))
    return any(abs(n - value) <= tol for n in _numbers(answer))


def expected(case):
    with connection.cursor() as cursor:
        cursor.execute(case['sql'])
        return cursor.fetchall()


def grade(case, rows, answer):
    if not rows or rows[0][0] is None:
        return False, 'reference query returned nothing'
    kind = case['check']
    if kind == 'names':
        names = [r[0] for r in rows]
        missing = [n for n in names if not _has_name(answer, n)]
        return not missing, f'expected {names}' + (f'; missing {missing}' if missing else '')
    if kind == 'number':
        value = rows[0][0]
        return _has_number(answer, value, case.get('tol', 0)), f'expected {value}'
    if kind == 'top':
        best = rows[0][1]
        tied = [r[0] for r in rows if r[1] == best]
        ok = any(_has_name(answer, n) for n in tied)
        return ok, f'expected one of {tied} ({best})'
    raise ValueError(kind)


class Command(BaseCommand):
    help = 'Score local model configurations on the known-answer question set (main/agent/eval_cases.py).'

    def add_arguments(self, parser):
        parser.add_argument('--config', action='append', required=True,
                            help='model[:+sql][:+think], e.g. "qwen3:8b+sql+think". Repeatable.')
        parser.add_argument('--only', help='Comma-separated case ids to run.')
        parser.add_argument('--log', help='Write every answer/tool call as JSON lines to this file.')
        parser.add_argument('--check-references', action='store_true',
                            help='Only run the reference queries and print the expected answers.')

    def handle(self, *args, **options):
        cases = CASES
        if options['only']:
            wanted = set(options['only'].split(','))
            cases = [c for c in CASES if c['id'] in wanted]

        refs = {}
        for case in cases:
            refs[case['id']] = expected(case)
            if options['check_references']:
                self.stdout.write(f"{case['id']:<4} {case['question']}\n     -> {refs[case['id']][:4]}")
        if options['check_references']:
            return

        log = open(options['log'], 'a', encoding='utf-8') if options['log'] else None
        summary = []
        for config in options['config']:
            model, *flags = config.split('+')
            agent = get_agent('local', model=model, sql='sql' in flags, think='think' in flags, timeout=600)
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n== {config} =='))
            results = []
            for case in cases:
                start = time.monotonic()
                try:
                    result = agent.ask(case['question'])
                    answer, calls, error = result.answer, result.tool_calls, None
                except AgentError as exc:
                    answer, calls, error = '', [], str(exc)
                seconds = time.monotonic() - start
                ok, why = grade(case, refs[case['id']], answer)
                sql_errors = sum(1 for c in calls if c.name == 'run_sql' and '"error"' in c.result[:20])
                results.append(dict(case=case['id'], level=case['level'], ok=ok, seconds=seconds,
                                    tools=len(calls), sql_errors=sql_errors))
                self.stdout.write(f"  [{'PASS' if ok else 'FAIL'}] {case['id']:<3} {seconds:5.1f}s "
                                  f"{len(calls)} tools  {why}")
                if not ok:
                    self.stdout.write(f"        answer: {answer[:220]!r}" + (f' error: {error}' if error else ''))
                if log:
                    log.write(json.dumps(dict(config=config, case=case['id'], question=case['question'],
                                              ok=ok, why=why, seconds=round(seconds, 1), answer=answer, error=error,
                                              calls=[dict(name=c.name, args=c.arguments, result=c.result[:1500])
                                                     for c in calls]), default=str) + '\n')
                    log.flush()
            summary.append((config, results))

        self.stdout.write(self.style.MIGRATE_HEADING('\n== summary =='))
        self.stdout.write(f"{'config':<28}{'total':>8}{'easy':>8}{'medium':>8}{'hard':>8}{'avg s':>8}{'sql err':>9}")
        for config, results in summary:
            def score(level=None):
                rs = [r for r in results if level is None or r['level'] == level]
                return f"{sum(r['ok'] for r in rs)}/{len(rs)}" if rs else '-'
            avg = sum(r['seconds'] for r in results) / len(results)
            errs = sum(r['sql_errors'] for r in results)
            self.stdout.write(f"{config:<28}{score():>8}{score('easy'):>8}{score('medium'):>8}"
                              f"{score('hard'):>8}{avg:>8.1f}{errs:>9}")
        if log:
            log.close()
