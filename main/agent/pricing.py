"""What a Claude API call costs, in USD. Checked against the pricing page on 2026-11-08.

A model that is not listed here is refused rather than guessed at, because the
daily budget is only as good as these numbers.
"""
from dataclasses import dataclass
from decimal import Decimal

PER_TOKEN = Decimal(1) / Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    input: Decimal
    cache_write: Decimal      # 5-minute cache
    cache_read: Decimal
    output: Decimal


PRICES = {
    'claude-haiku-5-5': Price(Decimal('0.10'), Decimal('0.125'), Decimal('0.01'), Decimal('0.50')),
    'claude-sonnet-5-5': Price(Decimal('2'), Decimal('2.50'), Decimal('0.10'), Decimal('10')),
}


def is_priced(model):
    return model in PRICES


def usage_cost(model, usage):
    """Cost of one response from its `usage` block. `input_tokens` excludes cached tokens."""
    price = PRICES[model]
    total = (
        (getattr(usage, 'input_tokens', 0) or 0) * price.input
        + (getattr(usage, 'cache_creation_input_tokens', 0) or 0) * price.cache_write
        + (getattr(usage, 'cache_read_input_tokens', 0) or 0) * price.cache_read
        + (getattr(usage, 'output_tokens', 0) or 0) * price.output
    )
    return total * PER_TOKEN


def worst_case_cost(model, input_tokens, max_tokens):
    """The most a call could cost: every input token written to cache, every output token used."""
    price = PRICES[model]
    return (input_tokens * price.cache_write + max_tokens * price.output) * PER_TOKEN
