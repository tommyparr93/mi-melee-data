"""Local LLM backend: talks to an Ollama server's /api/chat with tool calling."""
import requests

from .base import AgentError, AgentResult, BaseAgent, SYSTEM_PROMPT, ToolCall
from .tools import run_tool, tool_definitions


class OllamaAgent(BaseAgent):
    backend_name = 'local'

    def __init__(self, base_url='http://localhost:11434', model='qwen3:8b',
                 num_ctx=8192, timeout=180, session=None, **kwargs):
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.num_ctx = num_ctx
        self.timeout = timeout
        self.session = session or requests
        self.tools = [{'type': 'function', 'function': t} for t in tool_definitions()]

    def _chat(self, messages):
        try:
            resp = self.session.post(f'{self.base_url}/api/chat', json={
                'model': self.model,
                'messages': messages,
                'tools': self.tools,
                'stream': False,
                'think': False,
                'options': {'num_ctx': self.num_ctx, 'temperature': 0.2},
            }, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise AgentError(f'Could not reach Ollama at {self.base_url}: {exc}') from exc
        return resp.json()

    def ask(self, question, history=None):
        messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
        messages += [{'role': m['role'], 'content': m['content']} for m in (history or [])]
        messages.append({'role': 'user', 'content': question})
        result = AgentResult(answer='')

        for _ in range(self.max_steps):
            data = self._chat(messages)
            result.steps += 1
            result.input_tokens += data.get('prompt_eval_count', 0)
            result.output_tokens += data.get('eval_count', 0)
            message = data.get('message') or {}
            calls = message.get('tool_calls') or []
            if not calls:
                result.answer = (message.get('content') or '').strip()
                return result

            messages.append({'role': 'assistant', 'content': message.get('content') or '',
                             'tool_calls': calls})
            for call in calls:
                fn = call.get('function') or {}
                name, args = fn.get('name', ''), fn.get('arguments') or {}
                output = run_tool(name, args)
                result.tool_calls.append(ToolCall(name, args if isinstance(args, dict) else {}, output))
                messages.append({'role': 'tool', 'tool_name': name, 'content': output})

        return self._fallback_answer(result)
