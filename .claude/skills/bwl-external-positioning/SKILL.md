---
name: bwl-external-positioning
description: >
  Load when framing this project against the outside world: writing a paper, blog post, release note,
  README claim, or grant text; deciding what counts as "novel" or "beyond state-of-the-art"; choosing
  which datasets/numbers may be cited externally and with what licence and citation string; or answering
  "can we say we beat published unsupervised botnet detectors?", "is this method new?", "which numbers are
  safe to publish?", "what must we prove before claiming X?". Triggers: words like novelty, prior art,
  SOTA, baseline, licence, citation, reproducibility, publish, external claim.
---

# BWL external positioning: novelty, licences, and what may be claimed

This skill governs how the project is described **to anyone outside the team** — papers, blog posts,
release notes, README superlatives, grant copy. Its one job is to keep external claims **provably true,
conservatively scoped, and legally citable**. The default posture is *under*-claim: an over-claim that a
reviewer can falsify does more damage than a modest true statement.

Jargon is defined at first use; for deeper domain background see the sibling skills
`netflow-botnet-reference` (flows, botnets, C2, the datasets) and `bwl-detection-theory` (entropy, robust
z, isolation forests, Kneedle).

## When NOT to use this skill

| If you are… | Use instead |
|---|---|
| Actually *committing* a change or routing it through review | `bwl-change-control` (canonical HCOM protocol) |
| Deciding what evidence counts, tier discipline, adding a benchmark/test | `bwl-validation-and-qa` |
| Writing internal docs (FINDINGS/BENCHMARKS/README) in house style | `bwl-docs-and-writing` |
| Looking for open research problems / falsifiable milestones to *pursue* | `bwl-research-frontier` |
| Establishing the evidence bar hunch→result (predict-before-run) | `bwl-research-methodology` |
| Explaining the security/graph-anomaly theory itself | `netflow-botnet-reference`, `bwl-detection-theory` |

This skill answers "**what may we say to outsiders, and with what proof and citation?**" — not how to
build, measure, or commit. Anything that mints an external claim still passes through
`bwl-change-control` (data-scientist pair owns the narrative; human owner approves the claim).

---

## 1. The owner's definition of "beyond state-of-the-art"

Owner's working definition (2026-07-04): **beating published *unsupervised / label-free* baselines on
public botnet captures at rare-attack base rates — on the precision/recall frontier.**

Unpack every word, because each is a guard:

- **Unsupervised / label-free** — the detector never sees labels at run time (it ranks structurally
  unusual actors). We may *only* claim to beat baselines that are themselves label-free. Beating a
  *supervised* classifier is not our claim and must never be implied.
- **Published baselines** — a real, citable method with reported numbers, not a straw man. "Better than
  nothing" is not a result.
- **Public botnet captures** — the comparison must run on data an external reader can fetch (CTU-13,
  CICIDS2017). Numbers on private/licence-blocked data (Bournemouth) cannot back a public claim.
- **Rare-attack base rates** — the attack is a realistic ~3% minority, not a majority class. Precision at
  low prevalence is the hard part; a number at 50% prevalence proves little.
- **Precision/recall frontier** — both axes together. High recall at a 76% flag rate (an early stage of
  every arc here) is not beyond-SOTA; it is a filter that keeps almost everything.

> **Status of the claim today: NOT YET MADE.** We have strong *internal* numbers but have **not** run a
> head-to-head against a specific published unsupervised baseline's reported numbers on the same split.
> Until that comparison exists and is reviewed, "beyond SOTA" stays a *goal*, not a stated result. See
> `bwl-research-frontier` for the milestone.

---

## 2. What is genuinely novel here — vs known lineage

Be conservative. Everything below is a *combination and calibration* story, not a new primitive. The
honest headline is **"schema-agnostic, role-driven, explainable unsupervised detection with no
per-dataset feature engineering, plus an honest measurement harness"** — engineering novelty in
*composition and discipline*, not a new algorithm.

### Candidate novel contributions (what we may claim, carefully)

| Contribution | The precise, defensible claim | The guard (do not over-state) |
|---|---|---|
| **Schema-agnostic role-driven detection** | The engine picks actor/timestamp/entity columns **by shape, never by name**, so one pipeline scores CICIDS, CTU-13 and UNSW with **zero per-dataset feature engineering**. | Verified across 3 netflow datasets of *similar shape*. It does **not** transfer to web logs out of the box (Bournemouth negative). "Schema-agnostic" ≠ "domain-agnostic". |
| **Actor cardinality-ratio band gating BOTH paths** | One band (`ACTOR_MIN_RATIO`=0.02 … `ACTOR_MAX_RATIO`=0.5 on the column's cardinality ratio) types a column as a true actor, and the *same* band gates **both** per-entity baselining (`entity_monotony`) **and** graph endpoint selection (`asymmetric_degree`). One shape test excludes bounded categoricals (protocol, TCP state) below the band and per-row edge ids above it. | The band is the lever that fixed CTU-13 precision 0.041→0.978 by excluding degenerate `Proto`/`State` columns. But it is why the method goes **dormant** on Bournemouth (`session_id` falls below the band). Reusing one band for two jobs is the tidy part; it is not proven optimal. |
| **Source-fan-out-narrowed asymmetric degree with adaptive floor** | `asymmetric_degree` fires on a high-volume **source** endpoint whose out-degree exceeds an *adaptive* floor (99th percentile of the batch's own hub-subset degrees) **and** exceeds its in-degree by an order of magnitude (`DEGREE_ASYMMETRY`=10) **and** is monotone in service. Adaptive floor = self-calibrating per batch, not a fixed constant. | The *directional narrowing to source-only* was forced by the Rbot test (it over-fired on benign fan-in). Fan-out coverage is now two-family evidence; **fan-in coverage is a different rule (`entity_monotony`/hub gate) and is no-regression-guarded, not proved** (see §3). |
| **Honest measurement harness** | Detection is measured by **synthetic label-injection** (planting known-signature bots into real traffic for recall-per-archetype) **plus** a **tiered real-data registry** (only externally-labelled captures earn a row; synthetic numbers never do). | This is a *discipline* claim, not an accuracy claim. Its value is that it refuses to launder synthetic ~1.0 recall as field accuracy. |

### Known lineage we MUST credit

Anything published external must cite these; the actor graph is a *near-star graph outlier*, a
decades-old idea we operationalise, not invent.

| Prior work | What it establishes | Where cited in-repo |
|---|---|---|
| **OddBall** — Akoglu, McGlohon, Faloutsos, *PAKDD 2010*, LNCS 6119 pp.410–421 | Node degree/weight/egonet follow power laws; **near-star** nodes (high degree, sparse neighbour-interconnection) are the canonical structural anomaly — exactly what `asymmetric_degree` keys on. | `FINDINGS.md` References |
| **Graph anomaly survey** — Akoglu, Tong, Koutra, *DMKD* 29(3) 2015, DOI 10.1007/s10618-014-0365-y | Frames star/near-star and degree outliers as a primary structural-anomaly class. | `FINDINGS.md` References |
| **BotMiner** — Gu, Perdisci, Zhang, Lee, *USENIX Security 2008* pp.139–154 | Botnets are separable by **communication structure** (who-talks-to-whom), protocol-/payload-independent — the premise the actor graph operationalises. | `FINDINGS.md` References |
| **Extended Isolation Forest (EIF)** — Hariri, Kind, Brunner (isolation-forest lineage; `isotree`) | The ML tail path; the `eif` optional extra installs `isotree`. | `pyproject.toml` extra, `anomaly.py` |
| **Kneedle** — Satopää et al. | The knee detector behind the dynamic ML threshold (`threshold.py::dynamic_knee_threshold`). | `bwl-detection-theory`, `threshold.py` |
| **CTU-13 methodology** — García, Grill, Stiborek, Zunino, *Computers & Security* 45 (2014) 100–123 | The dataset + botnet-detection-comparison methodology our primary benchmarks use. | `ctu13_bot_benchmark.py`, both docs |

**Framing rule:** describe the contribution as *"we combine role-driven schema-agnosticism with a
near-star graph signal (OddBall lineage) and structure-based botnet detection (BotMiner lineage), gated
by a single actor-shape band, and measure it honestly."* Never present the star-anomaly or
structure-based ideas as ours.

---

## 3. What must be proven BEFORE claiming — claim → gate map

Each row is a claim someone might want to make, and the exact evidence gate that must be cleared first.
If the gate is not met, the claim is downgraded to the "may say instead" column.

| Tempting claim | Gate — what must be true | Status now | May say instead |
|---|---|---|---|
| "Generalises across botnet families" | ≥2 **independent** labelled families | **Have Neris + Rbot — but both are CTU-13 scenarios, same corpus, same capture method (Argus bidirectional NetFlow, CC-BY)** | "Generalises across the two CTU-13 families tested (Neris, Rbot); not yet across an independent corpus." |
| "Detects fan-in C2 botnets" | A **real, natively-labelled fan-in-bot** benchmark where the fan-out rule is not the one catching it | **Guarded, not proved.** Only real fan-in C2 is CICIDS (many hosts → `205.174.165.73`), where `entity_monotony` (not `asymmetric_degree`) carries it. Used as **no-regression evidence** only. | "Fan-in coverage is carried by `entity_monotony`/the hub gate and guarded by CICIDS no-regression; fan-in generality is not positively proved." |
| "`DEGREE_ASYMMETRY`=10 / 99th-pct floor are the right constants" | Behaviour characterised across scales | **Guardrails, not tuned/universal constants.** Hold for asymmetry factors ≈10–100 on one split + a synthetic broadcaster; over-fire below ≈10, vanish at ≥200. | "Limited-evidence guardrails validated on this split's scale range, not scale-free constants." |
| "Precision ~0.85–0.98 in production" | Field measurement against ground truth | **Impossible by construction** — the running system is unsupervised and has no labels; only the *benchmark* can measure precision because the *dataset* ships labels. | "Measured precision on this labelled capture; the deployed system ranks under uncertainty and cannot self-measure." |
| "Beats published unsupervised baselines" | Head-to-head vs a named baseline's reported numbers, same split, reviewed | **NOT DONE** (see §1). | "Strong internal numbers; the beyond-SOTA comparison is an open milestone." |
| Cite UNSW-NB15 as a bot result | It is a **broad-IDS** dataset (9 mixed attack families), not a bot capture | **UNSW numbers are NOT bot results** (recall 0.122, precision 0.198) | "Secondary generality probe on a broad-IDS dataset; not a bot-detection result." |
| Publish the Bournemouth numbers | A clear licence permitting redistribution/publication of derived numbers | **Licence-blocked** — CERTH ITI / Bournemouth University, research use *invited* but copyright *reserved*, no formal open licence | Keep internal. Do **not** put the numbers (recall 0.474 / precision 0.020 / flag 0.681) in any external artefact until licence is cleared. |
| "Scores are probabilities" / "flags are fraud" | — | **Never true.** Scores rank; a flag means "structurally unusual actor", not "confirmed bot/fraud". | "Anomaly ranking under uncertainty." |

**The Bournemouth negative is itself a *citable-internally* honest result**, and it is *good practice* to
report a negative — but only inside the team until the licence question is resolved. Recording where the
method *fails to transfer* (netflow→web logs, a **method limit** not a config bug — forcing `session_id`
active caught 0/11 bots) is part of the honest-positioning discipline, not an embarrassment to bury.

---

## 4. Licence + citation table (per dataset)

Datasets are **never redistributed** in this repo (all gitignored, skip-if-absent benchmarks). Any
external artefact that reports a number from a dataset must carry that dataset's citation string and
respect its licence.

| Dataset | Licence / terms | Redistribution | Citation string (use verbatim) |
|---|---|---|---|
| **CTU-13** (sc1 Neris, sc3 Rbot) | **CC-BY 2.0** (creativecommons.org/licenses/by/2.0/) | Data not redistributed here; CC-BY permits with attribution | S. García, M. Grill, J. Stiborek, A. Zunino, "An empirical comparison of botnet detection methods," *Computers & Security* 45 (2014) 100–123. Source: Stratosphere Laboratory, CTU University. |
| **CICIDS2017** (Friday-morning Ares) | CIC / University of New Brunswick **academic terms** (registration required) | Not redistributed; cite + link to CIC | I. Sharafaldin, A. H. Lashkari, A. A. Ghorbani, "Toward Generating a New Intrusion Detection Dataset and Intrusion Traffic Characterization," *4th Int. Conf. on Information Systems Security and Privacy (ICISSP)*, 2018. <https://www.unb.ca/cic/datasets/ids-2017.html> |
| **UNSW-NB15** (shard 1/4) | UNSW Canberra Cyber Range Lab **academic terms** | Not redistributed; raw shards from official source | N. Moustafa, J. Slay, "UNSW-NB15: a comprehensive data set for network intrusion detection systems," *MilCIS 2015*. <https://research.unsw.edu.au/projects/unsw-nb15-dataset> |
| **Bournemouth Web Bot Detection** | **UNCLEAR** — CERTH ITI / Bournemouth University (m4d.iti.gr, BORDaR record 272); research use invited, **copyright reserved, no formal open licence** | **Do NOT redistribute; do NOT publish derived numbers** until cleared | Iliou et al. (CERTH ITI / Bournemouth). *Licence must be resolved before any external citation.* |

> **UNVERIFIED — resolve before external use:** the Moustafa & Slay MilCIS 2015 title/venue and the
> Bournemouth "Iliou et al." authorship are from the roadmap brief, not the repo's own citation modules.
> The CTU-13 and CICIDS2017 strings ARE taken from the repo (`ctu13_bot_benchmark.py`, `BENCHMARKS.md`
> lines 508–517). Verify the two unverified strings against the primary source before putting them in
> any paper. (`grep -rn "Moustafa\|Iliou\|UNSW-NB15" evaluation/ bots_without_labels/`)

---

## 5. Reproducibility standard for ANY external claim

An external number is not citable unless a reader can regenerate it. Every published figure must ship the
whole recipe below. This mirrors what `BENCHMARKS.md` already does internally — the standard is "someone
outside the team can reproduce this from the paper alone."

Checklist — a claim is reproducible only if **all** are present:

- [ ] **Exact fetch command** for the dataset (curl/registration link), e.g. the CTU-13 `curl` to
      `mcfp.felk.cvut.cz/publicDatasets/CTU-Malware-Capture-Botnet-42/…/capture20110810.binetflow`.
- [ ] **Exact run command** with the `eif` extra, e.g.
      `uv run --extra eif python -m evaluation.run_benchmarks` (or a single `--only <name>`).
- [ ] **Fixed seeds** — the rare-attack mix and any sampling are deterministic (the benchmark harness
      builds a fixed `build_mix`); state the seed/row counts (e.g. n=62,000, 60,000 benign + 2,000 bot).
- [ ] **The `run_benchmarks` registry table row** — base rate, timestamp resolution, entity columns,
      recall/precision/flag rate — copied verbatim, number-for-number, from script output (never rounded
      "for effect").
- [ ] **Versioned constants** — the git commit *and* the constant values in force at measurement time:
      `ACTOR_MIN_RATIO=0.02`, `ACTOR_MAX_RATIO=0.5` (`features.py`), `DEGREE_ASYMMETRY=10`,
      `DEGREE_FLOOR_PERCENTILE=0.99`, `MIN_HUB_DEGREE=3`, `W_ASYMMETRIC_DEGREE=0.70` (`rules.py`).
- [ ] **Per-rule attribution included** — not just the headline. State which rule carried recall and
      where the residual false positives live (e.g. CTU-13 sc1: `asymmetric_degree` 2,000/2,000 clean,
      residual FPs are ML-only). A headline without attribution hides *which* mechanism earned the number.
- [ ] **The decision rule stated**: `is_bot = heuristic_score ≥ 0.70 OR ml_score > dynamic knee
      threshold` (Kneedle-derived, rate-capped at 2%). A precision number is meaningless without the
      operating point that produced it.

**Golden numbers as of commit 6fd33ac (cite the source doc, not memory):**

| Benchmark | Recall | Precision | Flag rate | Base rate | Source |
|---|---|---|---|---|---|
| CICIDS2017 / Ares | 0.998 | 0.846 | 0.037 | 0.032 | `BENCHMARKS.md` L45 |
| CTU-13 sc1 / Neris | 1.000 | 0.978 | 0.033 | 0.032 | `BENCHMARKS.md` L46 |
| CTU-13 sc3 / Rbot | 0.985 | 0.929 | 0.034 | 0.0323 | `BENCHMARKS.md` L47 |
| UNSW-NB15 (secondary, broad-IDS) | 0.122 | 0.198 | 0.020 | 0.032 | `BENCHMARKS.md` L48 |
| Bournemouth (INTERNAL ONLY) | 0.474 | 0.020 | 0.681 | 0.029 | `BENCHMARKS.md` L49 |

---

## 6. Pre-publication checklist (routes through `bwl-change-control`)

Any external artefact (paper, blog, release note, README superlative, grant text) is a **change** and
follows the HCOM team protocol. Ownership: the **data-scientist pair owns the analysis narrative** (one
drafts, the other reviews — mutual critique is the core control); the **human owner approves the claim**
and authorises any external release. The product manager is the only committer.

Run this before anything ships outside the team:

1. **Claim inventory** — list every factual/quantitative claim in the artefact. For each, name the
   evidence (a `BENCHMARKS.md` row, a reviewed HCOM finding). No orphan claims.
2. **Novelty audit (§2)** — every borrowed idea (star anomaly, structure-based detection, EIF, Kneedle,
   CTU-13 method) is credited. Nothing borrowed is framed as ours.
3. **Scope check (§3)** — no claim exceeds its gate. Generality = two CTU-13 families (say so). Fan-in =
   guarded, not proved. Constants = guardrails. No "production precision". No "beyond SOTA" until the
   head-to-head exists.
4. **Licence check (§4)** — every cited dataset has its citation string and a licence that permits the
   use. **Bournemouth numbers are stripped from any external artefact** until the licence is resolved.
5. **Reproducibility check (§5)** — fetch + run commands, seeds, versioned constants, per-rule
   attribution, decision rule, all present. Numbers copied verbatim from script output.
6. **Honest-negative check** — where the method fails (web-log domain transfer; UNSW as non-bot) is
   stated, not omitted. An artefact that reports only wins is dishonest by omission.
7. **Language sweep** — no "probability", no "fraud verdict", no "confirmed bot"; scores *rank*, flags
   mean "structurally unusual actor". (This is a non-negotiable from `bwl-change-control`.)
8. **Data-scientist reviewer sign-off**, then **human-owner approval** of the claim, then PM releases.
   A recorded exception (a direct-to-main artefact) is protocol debt — TODO follow-up G tracks the
   analogous unreviewed-change debt; do not create more.

If any step fails, the artefact does not ship. A blocked publication is a success of this process, not a
failure.

---

## Provenance and maintenance

Authored 2026-07-04. Repo at commit 6fd33ac (`Refresh roadmap: fold shipped arcs into a Shipped
section`). Numbers cross-checked against `evaluation/BENCHMARKS.md` and `evaluation/FINDINGS.md` at that
commit; constants read from source. British English; imperative runbook voice.

| Volatile fact | Re-verify with (read-only) |
|---|---|
| Benchmark numbers (CICIDS/CTU-13 sc1+sc3/UNSW/Bournemouth) | `sed -n '43,49p' evaluation/BENCHMARKS.md` |
| Actor-band constants (0.02 / 0.5) | `grep -n "ACTOR_MIN_RATIO\|ACTOR_MAX_RATIO" bots_without_labels/features.py` |
| Degree constants + asymmetric_degree weight (10 / 0.99 / 3 / 0.70) | `grep -n "DEGREE_ASYMMETRY\|DEGREE_FLOOR_PERCENTILE\|MIN_HUB_DEGREE\|W_ASYMMETRIC_DEGREE" bots_without_labels/rules.py` |
| Decision rule (0.70 heuristic OR knee, 2% cap) | `sed -n '20,60p' bots_without_labels/threshold.py` and the heuristic gate in `rules.py` |
| CTU-13 / CICIDS citation strings + licences | `sed -n '505,522p' evaluation/BENCHMARKS.md` |
| Bournemouth licence status (still unclear?) | `sed -n '438,453p' evaluation/BENCHMARKS.md` |
| Web-bot capability roadmap (item 12) / follow-up G | `grep -n "### 12\|### G" TODO.md` |
| Change-control ownership (PM commits; data-scientist narrative; owner approves) | `sed -n '111,135p' "development approach/team_instructions.md"` and lines 296–299 |
| Prior-art citations (OddBall/BotMiner/survey) | `sed -n '470,500p' evaluation/FINDINGS.md` |
| "Beyond-SOTA head-to-head" still not done? | `grep -rn "SOTA\|baseline\|beyond" evaluation/FINDINGS.md TODO.md` (expect no head-to-head claim) |
