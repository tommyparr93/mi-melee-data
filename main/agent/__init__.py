"""Natural-language agents over the Melee data. See `get_agent`."""
from django.conf import settings

from .base import AgentError, AgentResult, BaseAgent, BudgetExceeded, CreditExhausted

BACKENDS = ('claude', 'local')


def get_agent(backend=None, **overrides):
    """Build the configured agent: `claude` by default, or `local` (Ollama)."""
    backend = (backend or settings.AGENT_BACKEND).lower()
    if backend == 'claude':
        from .budget import DailyBudget
        from .claude import ClaudeAgent
        options = dict(api_key=settings.ANTHROPIC_API_KEY, model=settings.AGENT_CLAUDE_MODEL,
                       max_steps=settings.AGENT_MAX_STEPS, sql=settings.AGENT_SQL_ENABLED,
                       max_tokens=settings.AGENT_MAX_TOKENS, effort=settings.AGENT_CLAUDE_EFFORT)
        options.update(overrides)
        options.setdefault('budget', DailyBudget())
        return ClaudeAgent(**options)
    if backend == 'local':
        from .local import OllamaAgent
        options = dict(base_url=settings.OLLAMA_URL, model=settings.OLLAMA_MODEL,
                       max_steps=settings.AGENT_MAX_STEPS, sql=settings.AGENT_SQL_ENABLED,
                       think=settings.OLLAMA_THINK, num_ctx=settings.OLLAMA_NUM_CTX)
        options.update(overrides)
        return OllamaAgent(**options)
    raise AgentError(f'Unknown agent backend {backend!r}; choose one of {", ".join(BACKENDS)}.')
