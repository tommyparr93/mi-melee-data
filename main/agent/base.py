"""Backend-neutral agent interface.

An agent takes a question (plus optional earlier turns), lets a model call the
read-only tools in `tools.py`, and returns the final answer. Backends only
differ in how they talk to the model; the loop shape is shared here.
"""
from dataclasses import dataclass, field

SYSTEM_PROMPT = """\
You are the MiMeleeStats assistant. You answer questions about Super Smash Bros. \
Melee in Michigan using only the data returned by your tools: players, set results, \
head-to-heads, tournaments and power-ranking (PR) seasons from mimeleestats.com.

Rules:
- Never answer from memory about players, results or rankings. If a question needs data, call a tool.
- Players are identified by numeric id. Call find_player first to get ids from a tag; if several \
players match, pick the exact tag match or ask which one the user means.
- Every name, number and date in your answer must come from a tool result in this conversation. If you have not fetched it, call the tool; never fill gaps from memory.
- If a tool returns no data or an error, say so plainly. Do not guess or invent results.
- The data only covers tournaments tracked by the site, so say "in the tracked data" for records and totals.
- Keep answers short and concrete: lead with the answer, then a line or two of supporting numbers.
- Questions unrelated to Melee or this site's data: politely say you can only help with Melee stats."""


@dataclass
class ToolCall:
    name: str
    arguments: dict
    result: str


@dataclass
class AgentResult:
    answer: str
    tool_calls: list = field(default_factory=list)
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    stopped_early: bool = False


class AgentError(Exception):
    """The model backend was unreachable or returned something unusable."""


class BaseAgent:
    backend_name = 'base'

    def __init__(self, max_steps=6):
        self.max_steps = max_steps

    def ask(self, question, history=None):
        """Answer `question`. `history` is a list of {'role': 'user'|'assistant', 'content': str}."""
        raise NotImplementedError

    @staticmethod
    def _fallback_answer(result):
        result.stopped_early = True
        result.answer = result.answer or (
            'I could not finish looking that up. Try asking a narrower question.')
        return result
