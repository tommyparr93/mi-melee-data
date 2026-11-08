"""Per-visitor limits and the conversation log, both stored in the database.

AgentTurn rows do double duty: they are the audit log, and counting them is the
rate limit. Because the count lives in the database, every server process sees the
same numbers.
"""
import uuid
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import salted_hmac

from main.models import AgentTurn

MAX_HISTORY_CHARS = 1500
CONVERSATION_KEY = 'ask_tom_conversation'


class Rejected(Exception):
    def __init__(self, message, status=429):
        super().__init__(message)
        self.message = message
        self.status = status


def _hash(value):
    return salted_hmac('ask-tom', value or 'unknown').hexdigest()[:32]


def client_ip(request):
    """REMOTE_ADDR, unless a header set by our own reverse proxy is configured.

    X-Forwarded-For is never read by default because a visitor can send any value
    in it, which would let them dodge the per-IP limits.
    """
    header = settings.ASK_TOM_CLIENT_IP_HEADER
    return (header and request.META.get(header, '').strip()) or request.META.get('REMOTE_ADDR', 'unknown')


def conversation_id(request, new_chat=False):
    """Server-side conversation id. Stored in the session so a visitor can't pick one."""
    current = request.session.get(CONVERSATION_KEY)
    if new_chat or not current:
        current = uuid.uuid4().hex
        request.session[CONVERSATION_KEY] = current
    if not request.session.session_key:
        request.session.save()
    return current


def admit(request, question, conversation):
    """Record the turn, then count. Raises Rejected, leaving no row, if a limit is hit.

    Inserting before counting means simultaneous requests all see each other, so a
    burst errs on the side of being refused.
    """
    ip_hash, session_hash = _hash(client_ip(request)), _hash(request.session.session_key)
    turn = AgentTurn.objects.create(
        source='web', conversation_id=conversation, ip_hash=ip_hash, session_hash=session_hash,
        question=question, outcome='started')
    visitor = Q(ip_hash=ip_hash) | Q(session_hash=session_hash)
    now = timezone.now()
    recent = AgentTurn.objects.filter(visitor, source='web')
    message = None
    if recent.filter(created_at__gte=now - timedelta(minutes=1)).count() > settings.ASK_TOM_RATE_PER_MINUTE:
        message = "You're asking faster than I can keep up. Give it a minute and try again."
    elif recent.filter(created_at__gte=now - timedelta(days=1)).count() > settings.ASK_TOM_MESSAGES_PER_DAY:
        message = "You've reached today's question limit. Come back tomorrow."
    elif (AgentTurn.objects.filter(conversation_id=conversation).count()
          > settings.ASK_TOM_TURNS_PER_CONVERSATION):
        message = 'This chat has reached its limit. Start a new chat to keep going.'
    if message:
        turn.delete()
        raise Rejected(message)
    return turn


def conversation_history(conversation, before_id):
    """Earlier turns from our own log. A visitor can't forge what the assistant said."""
    pairs = settings.ASK_TOM_HISTORY_MESSAGES // 2
    turns = list(AgentTurn.objects.filter(conversation_id=conversation, outcome='ok', id__lt=before_id)
                 .order_by('-id')[:pairs])
    history = []
    for turn in reversed(turns):
        history.append({'role': 'user', 'content': turn.question[:MAX_HISTORY_CHARS]})
        history.append({'role': 'assistant', 'content': turn.answer[:MAX_HISTORY_CHARS]})
    return history


def finish_turn(turn, result, outcome, model, backend, seconds):
    turn.backend = backend
    turn.model = model
    turn.answer = result.answer
    turn.tools = [call.name for call in result.tool_calls]
    turn.steps = result.steps
    turn.input_tokens = result.input_tokens
    turn.output_tokens = result.output_tokens
    turn.cache_read_tokens = result.cache_read_tokens
    turn.cache_write_tokens = result.cache_write_tokens
    turn.cost_usd = result.cost_usd
    turn.outcome = outcome
    turn.seconds = seconds
    turn.save()
