"""'Ask Tom' chat page and its message endpoint."""
import json

from django.core.cache import cache
from django.http import JsonResponse
from django.views import generic
from django.views.decorators.http import require_POST

from main.agent import AgentError, get_agent

MAX_QUESTION_CHARS = 500
MAX_HISTORY_MESSAGES = 10          # 5 earlier exchanges is plenty of context for a small model
MAX_HISTORY_CHARS = 1500
RATE_LIMIT = 20                    # questions per client...
RATE_WINDOW = 10 * 60              # ...per 10 minutes
BUSY_LOCK_KEY = 'ask-tom-busy'
BUSY_LOCK_SECONDS = 150            # one local GPU: answer one question at a time

SUGGESTIONS = [
    "Who is ranked first in the latest power rankings?",
    "What's Zain's head to head against Mang0?",
    "Who won Tipped Off 16?",
    "Show me Ferrety's PR history",
]


class AskTomView(generic.TemplateView):
    template_name = 'main/ask_tom.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['suggestions'] = SUGGESTIONS
        context['max_chars'] = MAX_QUESTION_CHARS
        return context


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return forwarded.split(',')[0].strip() or request.META.get('REMOTE_ADDR', 'unknown')


def _rate_limited(request):
    key = f'ask-tom-rate:{_client_ip(request)}'
    cache.add(key, 0, RATE_WINDOW)
    try:
        return cache.incr(key) > RATE_LIMIT
    except ValueError:             # key expired between add and incr
        cache.set(key, 1, RATE_WINDOW)
        return False


def _clean_history(raw):
    """Only plain user/assistant text turns from the browser are passed to the model."""
    history = []
    if not isinstance(raw, list):
        return history
    for item in raw[-MAX_HISTORY_MESSAGES:]:
        if (isinstance(item, dict) and item.get('role') in ('user', 'assistant')
                and isinstance(item.get('content'), str) and item['content'].strip()):
            history.append({'role': item['role'], 'content': item['content'][:MAX_HISTORY_CHARS]})
    return history


@require_POST
def ask_tom_message(request):
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Bad request.'}, status=400)
    question = payload.get('question') if isinstance(payload, dict) else None
    if not isinstance(question, str) or not question.strip():
        return JsonResponse({'error': 'Type a question first.'}, status=400)
    question = question.strip()
    if len(question) > MAX_QUESTION_CHARS:
        return JsonResponse({'error': f'Questions are limited to {MAX_QUESTION_CHARS} characters.'}, status=400)

    if _rate_limited(request):
        return JsonResponse({'error': "You've asked a lot of questions. Give it a few minutes and try again."},
                            status=429)
    if not cache.add(BUSY_LOCK_KEY, 1, BUSY_LOCK_SECONDS):
        return JsonResponse({'error': 'Tom is answering someone else right now. Try again in a few seconds.'},
                            status=429)
    try:
        result = get_agent().ask(question, _clean_history(payload.get('history')))
    except AgentError:
        return JsonResponse({'error': 'Ask Tom is offline right now. Please try again later.'}, status=503)
    finally:
        cache.delete(BUSY_LOCK_KEY)

    return JsonResponse({
        'answer': result.answer or "I couldn't come up with an answer for that.",
        'looked_up': sorted({c.name for c in result.tool_calls}),
        'incomplete': result.stopped_early,
    })
