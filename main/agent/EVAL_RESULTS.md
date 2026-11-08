# Ask Tom eval

Run on 2026-11-08 against the local `melee_preview` data, Haiku only.

Two notes on the table below, which is the raw output of that run:

- **m6 was a grading bug, not a wrong answer.** The model correctly said Ohio with 34 events, but the grader only looked for "OH". The grader now accepts both, so the corrected score is 33/34.
- **a1 is a judgment call.** The model picked the Jam with 47 sets over one with 16 and said so, while the eval expected it to ask. Tom chose to keep that behavior, so a1 now passes if the model asks or says the tag is shared.

## Results

| model | ran | correct | easy | medium | multi-step | ambiguous | no-data | off-topic | injection | avg steps | avg cost | avg time | cache hit | total cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-haiku-5-5 | 34/34 | 32/34 | 6/6 | 8/9 | 6/6 | 2/3 | 2/2 | 3/3 | 5/5 | 2.6 | $0.0004 | 2.7s | 91% | $0.0128 |

Total spent on this run: $0.0128

### Failures: claude-haiku-5-5

- **m6** (medium): expected one of ['OH'] (34). Answer: '**Ohio** has hosted the most tournaments outside Michigan, with 34 in the data. Ontario (ON) is next with 32, then Kansas with 31 and Missouri with 29.'
- **a1** (ambiguous): should ask which player. Answer: 'Jam\'s set win rate is **42.9%** (15–20), excluding DQs. That\'s the best match for "Jam" ([Jam](/player/186865/)), who has 47 sets, well ahead of the other "Jam" tags (the next largest has 16).\n\nInclud'

## Follow-up: questions for the site's own tools

Six questions were added on 2026-11-08 for head-to-heads, journeys, records, the PR shortlist and the PR head-to-head table. Each expected answer was also compared with the tool's own output, and they matched. Those six, a1 and m6 were run on Haiku; the other 32 questions were not repeated.

All 8 passed on the first run, for $0.0052. That run exposed two problems, both fixed:

- Head-to-head results had no tournament ids, so the model wrote a broken link.
- The PR head-to-head table reported a player's matchups in a confusing order, so the tool now answers from that player's side.

After those fixes, t6 (Ferrety's record against PR-eligible players) failed once. The model wrote its own query and counted every PR-eligible set, including those against ineligible players, for 45-11 instead of 21-2. The schema notes now explain the difference, and t6 then passed 3 of 3 runs. Three runs is a small sample, so the fix is promising rather than proven.

The longest-win-streak list, common opponents and the schema tool still have no eval question.

Spending across all Haiku eval runs was $0.0216 for 48 questions, including repeats.
