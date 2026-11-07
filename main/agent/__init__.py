"""Natural-language agents over the Melee data. See `get_agent`."""
from django.conf import settings

from .base import AgentError, AgentResult, BaseAgent

BACKENDS = ('local', 'claude')


def get_agent(backend=None):
    """Build the configured agent. `local` (Ollama) is what the website will use;
    `claude` is for development and comparison."""
    backend = (backend or settings.AGENT_BACKEND).lower()
    if backend == 'local':
        from .local import OllamaAgent
        return OllamaAgent(base_url=settings.OLLAMA_URL, model=settings.OLLAMA_MODEL,
                           max_steps=settings.AGENT_MAX_STEPS)
    if backend == 'claude':
        from .claude import ClaudeAgent
        return ClaudeAgent(api_key=settings.ANTHROPIC_API_KEY, model=settings.AGENT_CLAUDE_MODEL,
                           max_steps=settings.AGENT_MAX_STEPS)
    raise AgentError(f'Unknown agent backend {backend!r}; choose one of {", ".join(BACKENDS)}.')
