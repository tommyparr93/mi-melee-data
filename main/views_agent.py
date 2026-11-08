"""'Ask Tom' chat page and its streaming message endpoint."""
import json
import logging
import time

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.views import generic
from django.views.decorators.http import require_POST

from main.agent import AgentError, AgentResult, BudgetExceeded, CreditExhausted, get_agent
from main.agent.base import TOOL_LABELS
from main.agent.links import add_links
from main.agent.limits import (
    CONVERSATION_KEY, Rejected, admit, conversation_history, conversation_id, finish_turn,
)
from main.models import AgentTurn

logger = logging.getLogger(__name__)

SUGGESTIONS = [
    "Who is ranked first in the latest power rankings?",
    "What's Zain's head to head against Mang0?",
    "Who won Tipped Off 16?",
    "Show me Ferrety's PR history",
]

NOT_ALLOWED_MESSAGE = 'Ask Tom is only available to site admins.'
DISABLED_MESSAGE = 'Ask Tom is switched off right now. Please check back later.'
BUDGET_MESSAGE = "Tom's done answering questions for today. Come back tomorrow!"
OFFLINE_MESSAGE = 'Ask Tom is offline right now. Please try again later.'
MAX_REPORT_CHARS = 500


class AskTomView(LoginRequiredMixin, UserPassesTestMixin, generic.TemplateView):
    template_name = 'main/ask_tom.html'

    def test_func(self):
        return self.request.user.is_superuser

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['suggestions'] = SUGGESTIONS
        context['max_chars'] = settings.ASK_TOM_MAX_INPUT_CHARS
        context['enabled'] = settings.ASK_TOM_ENABLED
        return context


def _line(**event):
    return json.dumps(event) + '\n'


def _stream_answer(request, turn, question, history):
    """Run the agent, turning its events into one JSON object per line.

    Internal details stay on the server: failures become a friendly message and the
    query text and cost go to staff (or local development) only.
    """
    result = AgentResult()
    outcome = 'abandoned'             # stays this way if the browser disconnects mid-answer
    backend, model = '', ''
    start = time.monotonic()
    try:
        agent = get_agent()
        backend, model = agent.backend_name, getattr(agent, 'model', '')
        for kind, value in agent.run(question, history, result=result):
            if kind == 'text':
                yield _line(type='text', text=value)
            elif kind == 'tool':
                yield _line(type='tool', label=TOOL_LABELS.get(value, 'data'))
        result.answer = add_links(result.answer, result.tool_calls)
        outcome = 'incomplete' if result.stopped_early else 'ok'
        done = {'answer': result.answer or "I couldn't come up with an answer for that.",
                'incomplete': result.stopped_early, 'turn_id': turn.id}
        if request.user.is_staff or settings.DEBUG:
            done['queries'] = [c.arguments.get('query', '') for c in result.tool_calls
                               if c.name == 'run_sql' and not c.result.startswith('{"error"')]
            done['meta'] = (f'{model} · {result.steps} steps · {time.monotonic() - start:.1f}s'
                            f' · ${result.cost_usd:.4f}')
        yield _line(type='done', **done)
    except BudgetExceeded:
        outcome = 'budget'
        yield _line(type='error', error=BUDGET_MESSAGE)
    except CreditExhausted:
        outcome = 'no_credit'
        yield _line(type='error', error=OFFLINE_MESSAGE)
    except AgentError as exc:
        outcome = 'error'
        logger.error('Ask Tom failed: %s', exc)
        yield _line(type='error', error=OFFLINE_MESSAGE)
    except Exception:
        outcome = 'error'
        logger.exception('Ask Tom crashed')
        yield _line(type='error', error=OFFLINE_MESSAGE)
    finally:
        finish_turn(turn, result, outcome, model, backend, round(time.monotonic() - start, 1))


@require_POST
def ask_tom_message(request):
    if not request.user.is_superuser:
        return JsonResponse({'error': NOT_ALLOWED_MESSAGE}, status=403)
    if not settings.ASK_TOM_ENABLED:
        return JsonResponse({'error': DISABLED_MESSAGE}, status=503)
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Bad request.'}, status=400)
    question = payload.get('question') if isinstance(payload, dict) else None
    if not isinstance(question, str) or not question.strip():
        return JsonResponse({'error': 'Type a question first.'}, status=400)
    question = question.strip()
    if len(question) > settings.ASK_TOM_MAX_INPUT_CHARS:
        return JsonResponse({'error': f'Questions are limited to {settings.ASK_TOM_MAX_INPUT_CHARS} characters.'},
                            status=400)

    # Checked before admitting, so a closed day doesn't use up anyone's rate limit.
    if settings.AGENT_BACKEND == 'claude':
        from main.agent.budget import DailyBudget
        try:
            DailyBudget().check_open()
        except BudgetExceeded:
            return JsonResponse({'error': BUDGET_MESSAGE}, status=429)
        except CreditExhausted:
            return JsonResponse({'error': OFFLINE_MESSAGE}, status=503)

    conversation = conversation_id(request, new_chat=bool(payload.get('new_chat')))
    try:
        turn = admit(request, question, conversation)
    except Rejected as rejected:
        return JsonResponse({'error': rejected.message}, status=rejected.status)

    history = conversation_history(conversation, turn.id)
    response = StreamingHttpResponse(_stream_answer(request, turn, question, history),
                                     content_type='application/x-ndjson')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'         # tell nginx not to hold the stream back
    return response


@require_POST
def ask_tom_report(request):
    """Flag an answer as bad. Only answers from the visitor's own current chat can be flagged."""
    if not request.user.is_superuser:
        return JsonResponse({'error': NOT_ALLOWED_MESSAGE}, status=403)
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Bad request.'}, status=400)
    turn_id = payload.get('turn_id') if isinstance(payload, dict) else None
    if not isinstance(turn_id, int):
        return JsonResponse({'error': 'Bad request.'}, status=400)
    turn = AgentTurn.objects.filter(pk=turn_id, source='web',
                                    conversation_id=request.session.get(CONVERSATION_KEY)).first()
    if turn is None:
        return JsonResponse({'error': 'That answer was not found.'}, status=404)
    turn.reported_at = timezone.now()
    turn.report_note = str(payload.get('note') or '').strip()[:MAX_REPORT_CHARS]
    turn.save(update_fields=['reported_at', 'report_note'])
    return JsonResponse({'ok': True})
