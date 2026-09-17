# Splendor AI Learning Workspace v1

- Status: **IMPLEMENTED / VERIFIED (local)** — teaching assets delivered; learner walkthrough/understanding not yet assessed. No product/research milestone acceptance.
- Baseline: `main@e081d550e273844daacca9858c8dd9a5e0784778`, clean before this round.
- Owner-date: 2026-09-17, user requested actual teach-skill goals and a webpage per goal.
- Scope: Chinese beginner-facing local learning workspace. Product authority remains `docs/human-live-league-v1.md`; this round does not authorize Slice A or reopen any research.

## Problem and evidence

The previous response supplied a conversational roadmap but did not create the teach skill's persistent mission, lesson pages or reference materials. The user explicitly asked to implement them. Learning preference: Splendor situations and problem solving, causal/data-flow order, including inference, training, PPO, self-play and historical research principles. Prior mathematics/programming knowledge remains unassessed.

## Initial design

Root `MISSION.md` is the compact learning compass; `RESOURCES.md` annotates sources; `NOTES.md` records teaching preferences. `lessons/index.html` links 16 numbered, complete short lessons, one per observable objective. Shared local CSS and JS live in `assets/`; `reference/` contains a glossary/data-flow sheet and a research map. Each lesson contains an illustrative Splendor problem, a mechanism, a source-linked project connection, one equal-length-choice quiz with immediate feedback, and a retrieval prompt. No learner account, server, network dependency, model or database access.

The mission operationalizes the user's explicit request as explaining a decision/data flow and interpreting the project's experiments. It does not assume an unconfirmed goal to implement algorithms. No learning record is created until the learner demonstrates understanding or states prior knowledge.

## Scope and non-goals

- In scope: meaningful first-pass lessons for all 16 objectives, primary/project sources, standalone navigation, responsive/print styling, accessible native controls, source-linked research chronology.
- Not in scope: a new Splendor engine, live replay integration, model execution/training, product UI changes, an exhaustive line-by-line treatment of every milestone, external deployment, automated claims of mastery.
- Examples use explicitly labeled simplified situations and invented numbers unless a source is named; they are not referee-certified replay positions or measured experiment outputs.

## Contracts and invariants

1. No change to engine, training implementation, product defaults, research verdicts or live League artifacts.
2. `FullState` stays referee-only. A sampled hidden world is not privileged knowledge of the actual world.
3. Inference != parameter update; self-play != PPO; fit to teacher != playing strength.
4. `n1` is forced-root successor evaluation, not a no-action current-state heuristic.
5. M18B is the implemented distributional Double-DQN subset, not every component of Rainbow.
6. PPO clipping limits a sample's improvement incentive; it is not a hard bound on every updated probability.
7. Teacher-relative corrections in M47S/M48A are not certified stronger play. Negative results retain their frozen scope.
8. No storage of answers or automatic completion/mastery badges. Feedback is local and transient.
9. `handoff.md` stays ignored/local-only; lesson assets are publishable source, not generated match data.

## Implementation plan

1. Verify sources and freeze objectives/source mapping.
2. Write mission/resources/notes and reusable lesson components.
3. Author 16 short lessons plus two references and an entry page.
4. Validate source links, objective coverage, quizzes and offline/browser behavior; update this record and local handoff.

## Acceptance gates

- G1: each mission objective maps to exactly one numbered lesson with non-placeholder content and working previous/next/reference links.
- G2: every lesson has a labeled goal, primary source, project source, practice feedback and a follow-up/retrieval prompt; choice lengths match within each quiz.
- G3: all local URLs and anchors resolve; local assets need no build, fetch, CDN or game service; no progress is fabricated.
- G4: automated checks cover quiz empty/right/wrong/retry behavior and PPO interactive arithmetic; browser checks when a usable browser is available. Clearly distinguish structural, DOM and visual evidence.
- G5: document reconciliation, `git diff --check`, ignored handoff and no product-code changes.
- Learner acceptance remains separate: owner opens first lesson and responds to an exercise. File creation cannot satisfy that gate.

## Iteration log

### 2026-09-17 — Initial scope

- Re-read teach SKILL plus MISSION/RESOURCES/LEARNING-RECORD formats.
- Verified baseline, clean tree, absent teaching paths, project documentation boundaries.
- Retrieved OpenAI RL/PPO material and original PPO, AlphaZero, Double-DQN, Rainbow and Deep Sets abstracts. Abstracts provide attribution, not full-paper verification.
- Read production PPO ratio/clipping implementation and source docs for self-play, same-actor transitions, n1 semantics and S3. Historical result labels will be attributed to tracked records, not presented as rerun experiments.

### 2026-09-17 — Implementation and validation

- Delivered all 16 objectives as substantive pages, not placeholder syllabus links. The reference map links 46 annotated records and every `docs/mNN*.md` file at the baseline; depth is deliberately grouped rather than claiming all experiments have been individually taught.
- Chinese C51 wording explicitly distinguishes **distributional / 分布型** from distributed computing. PPO teaching epsilon=0.2 is explicitly an illustration, not a claim about a run config.
- Browser harness uses an existing Chromium cache and CDP over `file://`; no dependency installation, local server, game process or network asset is needed. Failed reruns delete the old PASS report before execution, preventing stale success evidence.
- Screenshot iteration: initial PPO screenshot was taken before CSS smooth scrolling reached the calculator. Changed the harness's screenshot positioning to instant scroll, reran and inspected the actual calculator capture. No lesson behavior changed for this repair.
- Negative controls, both restored before the final suite: (1) replace PPO objective `min` with `max` → Node suite exit 1, **4 failures / 3 passes**; (2) disable actual DOM initialization → Chromium gate exit 1 at submit-enabled assertion (`true !== false`). The latter confirms tests exercise the real page wiring, not only detached helpers.

## Final implementation

- `MISSION.md`, `RESOURCES.md`, `NOTES.md`: mission, annotated sources, pacing and evidence rules. No `learning-records/` created, because there is no demonstrated learning yet.
- `lessons/index.html` plus `0001`–`0016`: observation, heuristic, search, hidden worlds, inference, supervised training, self-play, scaling, credit assignment, PPO, Double-DQN, representation, diagnostics, residuals, evaluation, S3 rollout.
- `assets/splendor-course.json`: 16 objective→page/source bindings; `mastery=not_assessed`.
- `assets/learning.css` / `learning.js`: shared responsive/print styles, native controls, local transient quiz feedback, positive/negative advantage PPO calculator. No tracking/storage/network calls.
- `reference/glossary.html` / `research-map.html`: terminology/data flow and 46 annotated historical record links.
- `scripts/check_learning.py`, `scripts/learning.test.cjs`, `scripts/check_learning_browser.cjs`: reproducible structural, arithmetic and actual-browser checks.
- 29 new tracked-delivery files; no existing product implementation modified. Local handoff and generated browser artifacts remain ignored.

## Validation and evidence

Commands executed from repository root after restoring both controls:

```text
python scripts/check_learning.py
  exit 0: 16 goals, 19 HTML pages, 405 local URLs, equal-length quiz choices,
  goal/source coverage, all mNN docs mapped, no remote runtime assets.
node --test --test-reporter=tap scripts/learning.test.cjs
  exit 0: 7 passed / 0 failed.
node --check assets/learning.js
  exit 0.
node --check scripts/check_learning_browser.cjs
  exit 0.
node scripts/check_learning_browser.cjs
  exit 0: Chromium file://; all 16 quizzes (empty / all 3 choices / reset),
  PPO positive + negative cases, keyboard Space radio selection,
  19 pages at 390px without viewport overflow, JavaScript-disabled native
  solution disclosure, 0 page HTTP requests, 0 uncaught exceptions.
git diff --check
  exit 0 (before staging).
git diff --cached --check
  exit 0; 29 staged files, all additions; NUL-containing files = 0.
git check-ignore -v handoff.md local-artifacts/splendor-ai-learning/browser-check.json
  exit 0; .gitignore lines 12 and 16 respectively.
```

Staged-scope inspection: no `handoff.md`, `local-artifacts/`, `crates/`,
`training/` or `apps/` files. Lesson/docs/scripts only. Delivery is committed
locally under the repository documentation contract; no push is requested or
performed. The exact delivery commit is discoverable in Git history and the
local handoff (not predicted in this document).

Local-only evidence: `local-artifacts/splendor-ai-learning/validation.log`,
`browser-check.json`, `index-desktop.png`, `lesson-01-mobile.png`,
`ppo-desktop.png`. Parent inspected the three final screenshots: desktop
entry, 390px first lesson and actual PPO calculator. This is a limited visual
inspection, not a human walkthrough, full accessibility audit or print proof.

SHA-256:

```text
assets/splendor-course.json
217b0fe086a8bb2eaf55ce3c6820958743fbbf1775171546857017b6118eb4ad
assets/learning.js
ec8e636056cbf93aace1bf20b649c5c9ed68d89ea678ae8000d9dc9a4d83a933
local-artifacts/splendor-ai-learning/browser-check.json
c66fa9904f20d874cc478a2bdc3dee540e5b83416f9a21d38f9d8dc465cfcf16
```

`powershell.exe -NoProfile -Command "Start-Process -FilePath 'E:\AUbuntuProject\project\splendor\lessons\index.html'"`
returned exit 0: the default-browser open request was issued. This does not
prove the user has viewed the page.

Rust/model/product suites were not run: this delivery changes only isolated
teaching assets and their validation scripts, not product or training code.
No historical experiment was rerun. No independent agent review was requested
or claimed.

## Result and decision

**IMPLEMENTED / VERIFIED (local)**. The requested mission and per-goal webpages
exist and pass the named checks. Educational content is a first-pass course,
not evidence that the user has mastered it. Existing product next-step order,
champion/default identities and closed research verdicts are unchanged.

## Known limitations

- First-pass conceptual coverage, not an exhaustive explanation of every code line or experiment configuration.
- Learner background and pace are unknown; subsequent lessons should adapt to actual answers.
- Historical evidence is read at the baseline; experiments are not rerun for teaching.
- Browser checks used one local Chromium build. Other browsers, screen readers, physical printing and the owner's manual walkthrough are not certified.
- Source Markdown/Python/Rust links may display as text or download in a browser; open in an editor when necessary.
- The 16 short lessons cover core principles; narrower per-experiment follow-up pages are a valid next teaching step, not a missing claim of universal depth.

## Next authorized gate

User opens `lessons/index.html`, begins `0001-observation.html` and shares the
exercise/transfer answer. Adapt pacing and create a learning record only from
that evidence. Existing Human Live League product authority is unchanged.
