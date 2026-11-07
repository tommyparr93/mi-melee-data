from django.core.management.base import BaseCommand, CommandError

from main.agent import BACKENDS, AgentError, get_agent


class Command(BaseCommand):
    help = 'Ask the Melee data agent a question from the terminal (local Ollama or Claude).'

    def add_arguments(self, parser):
        parser.add_argument('question', nargs='*', help='Question to ask. Omit for an interactive chat.')
        parser.add_argument('--backend', choices=BACKENDS,
                            help='Agent backend (default: AGENT_BACKEND setting).')
        parser.add_argument('--verbose', action='store_true', help='Show each tool call and its result.')

    def handle(self, *args, **options):
        try:
            agent = get_agent(options['backend'])
        except AgentError as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.NOTICE(f'backend: {agent.backend_name} ({agent.model})'))

        if options['question']:
            self._ask(agent, ' '.join(options['question']), None, options['verbose'])
            return

        history = []
        self.stdout.write('Interactive chat. Blank line or Ctrl+C to quit.')
        while True:
            try:
                question = input('\n> ').strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not question:
                break
            answer = self._ask(agent, question, history, options['verbose'])
            if answer is not None:
                history += [{'role': 'user', 'content': question},
                            {'role': 'assistant', 'content': answer}]

    def _ask(self, agent, question, history, verbose):
        try:
            result = agent.ask(question, history)
        except AgentError as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            return None
        if verbose:
            for call in result.tool_calls:
                preview = call.result if len(call.result) <= 300 else call.result[:300] + '...'
                self.stdout.write(self.style.HTTP_INFO(f'  tool {call.name}({call.arguments}) -> {preview}'))
        self.stdout.write(f'\n{result.answer}\n')
        self.stdout.write(self.style.NOTICE(
            f'[{result.steps} step(s), {len(result.tool_calls)} tool call(s), '
            f'{result.input_tokens} in / {result.output_tokens} out tokens]'))
        return result.answer
