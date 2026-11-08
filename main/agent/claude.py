"""Claude backend: a hand-written tool loop over the Messages API.

Owning the loop is what lets every model call pass through the budget check, and
lets the loop stop at the step cap.
"""
import json
import logging

from django.conf import settings

from . import pricing
from .base import AgentError, AgentResult, BaseAgent, CreditExhausted, ToolCall, date_note
from .tools import run_tool, tool_definitions

try:
    import anthropic
except ImportError:              # only needed when this backend is selected
    anthropic = None

logger = logging.getLogger(__name__)

EPHEMERAL = {'type': 'ephemeral'}
REFUSAL_ANSWER = "I can't help with that one. Ask me about Michigan Melee players, tournaments or rankings."


def _is_credit_error(exc):
    return (exc.status_code == 402 or getattr(exc, 'type', None) == 'billing_error'
            or 'credit balance' in str(exc).lower())


class ClaudeAgent(BaseAgent):
    backend_name = 'claude'

    def __init__(self, api_key=None, model='claude-haiku-5-5', max_tokens=1024, effort='low',
                 client=None, budget=None, tool_runner=run_tool, **kwargs):
        super().__init__(**kwargs)
        if not pricing.is_priced(model):
            raise AgentError(f'No pricing is configured for {model}; add it to pricing.py.')
        if client is None:
            if anthropic is None:
                raise AgentError('The anthropic package is not installed; '
                                 'run: pip install -r requirements-agent.txt')
            if not api_key:
                raise AgentError('ANTHROPIC_API_KEY is not set.')
            # One retry for a brief overload. The SDK never retries a billing error.
            client = anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=45.0)
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self.budget = budget
        self.tool_runner = tool_runner
        self.tools = [{'name': t['name'], 'description': t['description'],
                       'input_schema': t['parameters']} for t in tool_definitions(sql=self.sql)]
        # Everything up to this breakpoint is identical on every request, so it is cached.
        self.stable_system = {'type': 'text', 'text': self.system_prompt, 'cache_control': EPHEMERAL}
        self._prefix_chars = len(self.system_prompt) + len(json.dumps(self.tools))

    def _reserve(self, messages):
        """Hold the most this call could cost, before making it."""
        if self.budget is None:
            return None
        # Roughly 3.5 characters per token, so dividing by 3 overestimates on purpose.
        input_tokens = (self._prefix_chars + len(json.dumps(messages, default=str))) // 3
        return self.budget.reserve(pricing.worst_case_cost(self.model, input_tokens, self.max_tokens))

    def _settle(self, reservation, actual):
        if reservation is not None:
            self.budget.settle(reservation, actual)

    def _call(self, system, messages, result):
        """Stream one model call, yielding text chunks and then ('message', response)."""
        reservation = self._reserve(messages)
        response, started = None, False
        try:
            with self.client.messages.stream(
                    model=self.model, max_tokens=self.max_tokens, system=system, tools=self.tools,
                    messages=messages, cache_control=EPHEMERAL,
                    output_config={'effort': self.effort}) as stream:
                for event in stream:
                    started = True
                    if event.type == 'text':
                        yield 'text', event.text
                response = stream.get_final_message()
        except Exception as exc:
            if anthropic is not None and isinstance(exc, anthropic.APIStatusError) and _is_credit_error(exc):
                logger.error('Ask Tom: the Claude account is out of credit.')
                if self.budget is not None:
                    self.budget.mark_credit_exhausted()
                raise CreditExhausted('out of credit') from exc
            if anthropic is not None and isinstance(exc, anthropic.APIError):
                raise AgentError(f'Claude API call failed: {exc}') from exc
            raise
        finally:
            if response is not None:
                cost = pricing.usage_cost(self.model, response.usage)
                self._record_usage(result, response.usage, cost)
                self._settle(reservation, cost)
            else:
                # Failed or abandoned. A stream that had started may already be billed.
                self._settle(reservation, reservation.amount if (started and reservation) else 0)
        yield 'message', response

    @staticmethod
    def _record_usage(result, usage, cost):
        result.input_tokens += usage.input_tokens or 0
        result.output_tokens += usage.output_tokens or 0
        result.cache_read_tokens += getattr(usage, 'cache_read_input_tokens', 0) or 0
        result.cache_write_tokens += getattr(usage, 'cache_creation_input_tokens', 0) or 0
        result.cost_usd += cost

    def run(self, question, history=None, result=None):
        result = result if result is not None else AgentResult()
        messages = [{'role': m['role'], 'content': m['content']} for m in (history or [])]
        messages.append({'role': 'user', 'content': question})
        system = [self.stable_system, {'type': 'text', 'text': date_note()}]

        for _ in range(self.max_steps):
            response = None
            for kind, value in self._call(system, messages, result):
                if kind == 'text':
                    yield kind, value
                else:
                    response = value
            result.steps += 1

            text = ''.join(b.text for b in response.content if b.type == 'text').strip()
            tool_uses = [b for b in response.content if b.type == 'tool_use']

            if response.stop_reason == 'refusal':
                result.answer = REFUSAL_ANSWER
                yield 'done', result
                return
            if response.stop_reason == 'max_tokens':
                # Any tool call in this response is cut off, so it must not be run.
                result.answer = text
                yield 'done', self._give_up(result)
                return
            if response.stop_reason != 'tool_use' or not tool_uses:
                result.answer = text
                yield 'done', result
                return

            messages.append({'role': 'assistant', 'content': response.content})
            outputs = []
            for block in tool_uses:
                yield 'tool', block.name
                output = self.tool_runner(block.name, block.input)
                result.tool_calls.append(ToolCall(block.name, dict(block.input), output))
                outputs.append({'type': 'tool_result', 'tool_use_id': block.id, 'content': output,
                                'is_error': output.startswith('{"error"')})
            messages.append({'role': 'user', 'content': outputs})

        yield 'done', self._give_up(result)
