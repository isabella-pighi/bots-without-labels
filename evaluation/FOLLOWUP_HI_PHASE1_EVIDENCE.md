# Follow-ups H and I — Phase 1 evidence package (actor/vocabulary/content residuals)

**Status: Phase 1 evidence for review. No detector behaviour changed** — the only
code added is the offline diagnostic `evaluation/actor_residual_probe.py`; nothing
under `bots_without_labels/` was touched, so every registry number is unchanged by
construction. All fixture figures below are **mechanism evidence on unlabelled
synthetic logs**, never precision/recall claims. Bournemouth figures are
**internal/provisional** (licence pending) wherever they appear.

Reproduce everything in this note:

```bash
uv run --extra eif python -m evaluation.actor_residual_probe          # fixtures only
uv run --extra eif python -m evaluation.actor_residual_probe --real   # + real captures (skip-if-absent)
```

## Method

Three residuals of the scale-invariant actor selection (TODO follow-ups H and I)
were isolated with minimal fixtures, then the candidate separating signals the
brief names — recurrence structure, cross-column co-occurrence/counterpart
structure, and token grammar — were measured offline on the fixtures and on the
real captures. Predictions were frozen in writing before each run
(predict-before-run, `bwl-proof-and-analysis-toolkit` Recipe 6); the two
divergences that occurred are recorded below, not overwritten. Nothing here uses
`distinct / n_rows`.

The probe's counterpart-selectivity signal is defined as observed counterpart
coverage divided by the coverage independent draws from the counterpart column's
marginal would give the same row count: ~1 means a value mixes freely
(vocabulary/content-like), well below 1 means it keeps to its own counterparts
(identity-like).

## Residual H — integer-coded identifiers

**Mechanism confirmed by minimal pairs.** The toolkit broadcaster fixture with
dotted addresses selects `[src, dst]` as endpoints and `asymmetric_degree` fires
on exactly the 90 fan-out rows. Re-coding the same addresses as integers
(`10.0.0.1` → `167772161`) — identical behaviour, different value coding — types
both columns `numeric`: no entity columns, no endpoints, `asymmetric_degree`
fires 0. Likewise a 40-session log: token ids (`sess1001`) give
`_entity_columns = [session_id]`; bare integers (`1001`) give `[]`.

**Candidate fix audited: route numeric columns through the existing actor tests.**
The probe applies the endpoint tests (distinct, recurrence, repeat-mass,
vocabulary shape) to every numeric column of the real mixes, as strings. Result —
the tests do **not** discriminate identifiers from recurring discrete
measurements:

| Capture | Numeric columns that WOULD qualify as endpoints |
|---|---|
| CTU-13 sc1 mix | **5** — `Dport` (repeat-mass 0.884), `Dur` (0.448), `TotPkts`, `TotBytes`, `SrcBytes` |
| CICIDS2017 Ares mix | **53** — ports, packet lengths, IATs, header lengths, window sizes, … |
| UNSW-NB15 mix | **11** — `dsport`, `sbytes`, `dbytes`, packet counts, RTTs, … |
| Bournemouth web mix | 0 (`bytes` escapes only because its 188 distinct values sit under `VOCAB_MAX_DISTINCT = 200` — a fragile margin) |

So naive integer routing would change actor selection on **every protected flow
capture** — not bit-identical, and it would flood the entity/actor machinery with
dozens of measurement pseudo-actors.

**Could a further signal rescue it?** Measured on the same runs:

- *Counterpart selectivity* overlaps hopelessly: the genuine `Source IP` /
  `Destination IP` score 0.644 / 0.688 on CICIDS and 1.093 / 1.338 on CTU-13,
  while measurement columns span 0.022–1.57 (e.g. `Init_Win_bytes_forward`
  0.272 — *more* selective than `Source IP`).
- *Digit-length uniformity* has thin daylight: integer-coded IPs and ids measure
  1.0, real measurement/port columns ≤ 0.894 — but the margin is one capture
  family wide, and a false admit is a flood, not a nudge.

**Verdict (H): recorded negative for heuristic inference.** No measured
observable signal separates an integer-coded identifier from a recurring
discrete measurement with a margin worth shipping. The Phase 2 recommendation is
the explicit schema override (`--entity-column`, TODO item 4): deterministic,
zero risk to the protected rows, and it also covers the H2 case (a small
bare-integer pool) that shape tests cannot reach even as strings. Digit-length
uniformity is recorded as a research-only candidate that would need a real
labelled capture with integer-coded identifiers before any implementation.

## Residual Ia — short unstructured actor ids vs bounded vocabulary

**Mechanism confirmed.** A closed pool of 60 short usernames (each recurring 12
times, each talking to 3 of 12 servers) is excluded as a vocabulary; the same
log with `usr-1001`-style ids is admitted to both selection paths.

**Grammar cannot separate — by construction and by measurement.** The fixture's
`cmd` column is a true vocabulary with the *identical* frequency profile (60
distinct, each exactly 12 rows) and identical grammar profile (structured
fraction 0.0, no digits, no separators) as the username column. Frequency and
shape are blind here; this is the ambiguity the residual names.

**Co-occurrence structure does separate — on this fixture.** Counterpart
selectivity vs the server column: usernames **0.388** (each keeps to its 3
servers), `cmd` **1.021** (mixes freely). The frequency-identical pair is
separable in principle by counterpart structure.

**But the signal does not generalise as a threshold.** On the real captures,
*genuine open-population actors* measure ~1 (CTU `SrcAddr` 1.093, `DstAddr`
1.338; Bournemouth `session_id` vs path 0.929) — real actors in open traffic mix
as freely as vocabularies do, so any fixed cut that keeps the fixture's actors
would misread the tracked captures, and no labelled real capture with a
short-unstructured actor pool exists in the current dataset pool to validate
against (see the rejected-datasets table in `evaluation/BENCHMARKS.md`).

**Verdict (Ia): separable in principle (co-occurrence), not shippable as a
heuristic on current evidence.** Recommendation: the explicit
`--entity-column` override is the Phase 2 fix; the selectivity signal is
recorded as a research candidate pending a real capture that exercises it.

## Residual Ib — raw path/content columns admitted as pseudo-actors

**Mechanism confirmed — and sharper than previously recorded.** On a benign
web-log fixture in Apache column order, the raw `path` column is admitted to
*both* selection paths, and because `path` precedes `session_id` in the schema,
it takes the **directional source seat** of `asymmetric_degree`. The rule then
fires on 84 rows of a purely benign 1,123-row log, e.g.:

    asymmetric_degree: path '/login' reaches 36 distinct counterparts as a
    source while only 0 reach it back, on a monotone service

On the real Bournemouth mix (internal/provisional) the same mechanism fires
`asymmetric_degree` on **53,467 of 58,279 rows** (e.g. `/css/main.css`
"reaching" 274 counterparts) — a first-class driver of the registry row's 0.918
flag rate, alongside the session-monotony (8,191 `entity_monotony` fires) and
timing over-fires already recorded in `evaluation/FINDINGS.md`. A content column
in the identity seat is not a passive residual; it actively powers a STRONG
rule. (Divergences vs prediction, recorded: on the first fixture variant with
per-row random bytes nothing fired — content only over-fires when its behaviour
is genuinely monotone, as static pages are; and `entity_monotony` stayed at 0 on
the fixture, the over-fire channel being the graph rule instead.)

**Token grammar separates cleanly and consistently.** Leading-separator fraction
of distinct values (a value starting with `. : _ - /`):

| Column | leading-separator | mean separators/value |
|---|---|---|
| fixture `path` | **1.000** | 2.43 |
| Bournemouth `path` | **1.000** | 5.55 |
| every admitted actor/entity column measured (IPs, session ids, usernames variant) | 0.000 | 0–3 |
| `user_agent` (non-path web column, measured for contrast; not an admitted actor) | 0.000 | 11.5 |

**Counterpart selectivity does not separate on web data** (~1.0 on both `path`
and `session_id`, fixture and Bournemouth) — sessions browse a shared catalogue
freely. The separating signal for content is grammar, exactly where grammar
failed for Ia; the two signals are complementary, not interchangeable.

**Verdict (Ib): separable by observable signal.** The Phase 2 candidate is a
value-grammar extension of the existing `_is_content_column` guard (which is
already the designed home for content exclusion, currently role/derivation-only):
demote an actor candidate whose distinct values overwhelmingly begin with a
separator character. This is a value-shape property, not a column-name or
dataset branch, so it sits inside the architecture contract. An explicit
`--content-column` override remains the deterministic fallback and should ship
alongside regardless.

## Heuristic inference vs explicit schema override

| Residual | Heuristic available? | Override (`--entity-column` / `--content-column`) |
|---|---|---|
| H (integer-coded ids) | **No** — recorded negative; existing tests admit dozens of measurement columns; auxiliary signals overlap or have unvalidated thin margins | **Recommended fix** (couples with TODO item 4) |
| Ia (short unstructured pools) | **Not on current evidence** — co-occurrence separates the fixture but no real capture can validate a threshold | **Recommended fix** |
| Ib (raw path content) | **Yes** — leading-separator grammar, 1.0 vs 0.0 on every column measured, fixture and real | Override still worth shipping as the deterministic escape hatch |

Overrides are heuristic-free, deterministic, and default-off — with no flags
passed, behaviour is bit-identical everywhere, which is why they are the safe
carrier for H and Ia.

## PRE_RUN_PREDICTIONS — all eleven registry rows

Written **before any Phase 2 implementation is proposed or started**, per the
task brief. Current measured values are copied from `evaluation/BENCHMARKS.md`
(post fallback-hub-gate). The seven strong rows are protected with
**bit-identical** expectation; the single deliberate target is Bournemouth,
already the registry's recorded negative — moving it is the point of Ib and is
flagged here for escalation before any implementation.

Candidate designs predicted:

- **Design A — schema overrides only** (`--entity-column` / `--content-column`,
  TODO item 4): default-off ⇒ **all eleven rows bit-identical** (no benchmark
  passes an override).
- **Design B — Ib grammar demotion in `_is_content_column`**: demotes admitted
  actor candidates whose distinct values overwhelmingly start with a separator.

| # | Row (current measured recall / precision / flag) | Design B prediction |
|---|---|---|
| 1 | CICIDS Ares 0.998 / 0.879 / 0.036 | **Bit-identical** — admitted endpoints are IP columns, leading-separator 0.000 |
| 2 | CTU-13 sc1 Neris 1.000 / 0.971 / 0.033 | **Bit-identical** — same grounds (`SrcAddr`/`DstAddr` 0.000) |
| 3 | CTU-13 sc3 Rbot 0.985 / 0.9319 / 0.034 | **Bit-identical** — same schema as sc1 |
| 4 | UNSW-NB15 1.000 / 0.519 / 0.062 | **Bit-identical** — entity columns `srcip`/`dstip`, leading-separator 0.000 |
| 5 | cicids_portscan 1.000 / 0.585 / 0.055 | **Bit-identical** — CICIDS schema, no path-shaped column |
| 6 | cicids_ddos 1.000 / 0.786 / 0.041 | **Bit-identical** — same |
| 7 | cicids_bruteforce 1.000 / 0.600 / 0.054 | **Bit-identical** — same |
| 8 | cicids_webattacks 0.000 / 0.000 / 0.005 | **Bit-identical** — same (weak row, no deliberate target) |
| 9 | cicids_dos 0.040 / 0.046 / 0.028 | **Bit-identical** — same (weak row, no deliberate target) |
| 10 | cicids_infiltration 0.472 / 0.053 / 0.005 | **Bit-identical** — same (weak row, no deliberate target) |
| 11 | Bournemouth 0.873 / 0.028 / 0.918 *(provisional)* | **Deliberate target.** `path` demoted ⇒ `asymmetric_degree` loses its pseudo-source (53,467 fires) and, with `session_id` the only remaining endpoint, goes dormant. Predicted **direction**: flag rate falls materially below 0.918; recall likely falls too (some bot rows were carried by the path fire); the row **remains a domain-transfer negative** — session monotony and timing over-fires persist (method limit, TODO item 12). No positive precision claim is predicted. |

Escalation rule restated: if any of rows 1–7 deviates from bit-identical in a
Phase 2 diff run, that is a blocker — stop and escalate before proceeding, per
the task brief. Rows 8–10 are also predicted bit-identical; a deviation there is
a surprise to attribute, not a silent acceptance. Exact Bournemouth numbers are
deliberately *not* predicted beyond direction: pinning a number to a
licence-pending, 11-bot-session capture would be false precision — Phase 2 must
refine this prediction (with the same direction) immediately before its
verification run.

## Limits of this evidence

- Fixture behaviour is mechanism evidence on unlabelled synthetic logs; no
  precision/recall is claimed anywhere in this note for them.
- Bournemouth figures (53,467 / 8,191 fires; 0.918 flag rate) are
  internal/provisional pending the licence decision, as everywhere else in the
  repo.
- The leading-separator constant that Design B would need is a limited-evidence
  guardrail (two web logs, four flow captures, all measuring 1.0 vs 0.000); like
  `DEGREE_ASYMMETRY`, it must be documented as such and swept before shipping.
- Counterpart selectivity is validated as a separator only on a closed-pool
  fixture; its real-capture values contradict a universal threshold. Do not
  ship it without a labelled capture that exercises the closed-pool case.

*Authored 2026-07-15 on branch `agent/followup-hi-phase1-actor-residuals`;
probe outputs reproduced by the commands at the top of this note.*
