"""Claude backend (Anthropic SDK). Intended for development and comparison testing."""
from .base import AgentError, AgentResult, BaseAgent, SYSTEM_PROMPT, ToolCall
from .tools import run_tool, tool_definitions


class ClaudeAgent(BaseAgent):
    backend_name = 'claude'

    def __init__(self, api_key=None, model='claude-sonnet-5-5', max_tokens=1024,
                 client=None, **kwargs):
        super().__init__(**kwargs)
        self.model = model
        self.max_tokens = max_tokens
        if client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise AgentError('The anthropic package is not installed; '
                                 'run: pip install -r requirements-agent.txt') from exc
            if not api_key:
                raise AgentError('ANTHROPIC_API_KEY is not set.')
            client = anthropic.Anthropic(api_key=api_key)
        self.client = client
        self.tools = [{'name': t['name'], 'description': t['description'],
                       'input_schema': t['parameters']} for t in tool_definitions()]

    def ask(self, question, history=None):
        messages = [{'role': m['role'], 'content': m['content']} for m in (history or [])]
        messages.append({'role': 'user', 'content': question})
        result = AgentResult(answer='')

        for _ in range(self.max_steps):
            try:
                response = self.client.messages.create(
                    model=self.model, max_tokens=self.max_tokens, system=SYSTEM_PROMPT,
                    tools=self.tools, messages=messages)
            except Exception as exc:  # SDK raises several distinct error types
                raise AgentError(f'Claude API call failed: {exc}') from exc
            result.steps += 1
            result.input_tokens += response.usage.input_tokens
            result.output_tokens += response.usage.output_tokens

            text = ''.join(b.text for b in response.content if b.type == 'text').strip()
            tool_uses = [b for b in response.content if b.type == 'tool_use']
            if response.stop_reason != 'tool_use' or not tool_uses:
                result.answer = text
                return result

            messages.append({'role': 'assistant', 'content': response.content})
            outputs = []
            for block in tool_uses:
                output = run_tool(block.name, block.input)
                result.tool_calls.append(ToolCall(block.name, dict(block.input), output))
                outputs.append({'type': 'tool_result', 'tool_use_id': block.id, 'content': output})
            messages.append({'role': 'user', 'content': outputs})

        return self._fallback_answer(result)
