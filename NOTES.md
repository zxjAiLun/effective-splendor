# Teaching Notes

## Stated preferences

- 2026-09-17: Use mattpocock's `productivity/teach` skill, not just a chat lecture. User explicitly requested learning objectives and a webpage for each objective.
- Chinese, beginner-friendly; explain through Splendor situations/problem solving in causal or data-flow order. Include inference, training, RL, PPO, self-play and principles behind the project's research.
- Avoid treating self-deprecating language as evidence of inability. Prior programming/mathematics/game-rule fluency remains unknown.

## Delivery and pacing

- Entry: `lessons/index.html`. Begin with `lessons/0001-observation.html`; 16 pages are a course map, not a demand to complete them in one sitting.
- First read the situation, then predict before opening the explanation. Use one quiz and a short free-response transfer question per page.
- Next session: ask for a from-memory explanation of the previous distinction before new content. Suggested next-day and one-week retrieval prompts are guidance, not a scheduled task.
- If an answer reveals confusion, reduce scope and give a contrasting Splendor example. Do not increase jargon because a page was opened.
- No localStorage, telemetry, backend, auto completion badge or file writes in lesson JS. Quiz feedback is transient. The assistant cannot observe answers unless the user shares them.

## Learning records

`learning-records/` is intentionally not created yet. The skill requires real evidence of understanding, stated prior knowledge, a corrected misconception or a changed mission—not a session activity log. After such evidence, create the next numbered Markdown record using the skill's concise format and record exactly what was demonstrated.

## Source and scope discipline

- Baseline `e081d550e273844daacca9858c8dd9a5e0784778`. No experiment was rerun for this course.
- All invented positions/probabilities are labeled teaching examples, not legal replay fixtures or measured model outputs.
- `n1` executes each forced root action before static scoring. Never label it a pure current-state no-search policy.
- PPO numeric slider uses epsilon=0.2 for teaching; it is not a claim about a project's config. Clipping is not a hard probability cap.
- Negative research outcomes stay bounded. M39 did not validate improvement; M48 closed the budgeted neural-evaluator route; neither proves all neural/RL approaches impossible.
- The S3 field reference is not an unlimited claim of global optimality, nor a direct reward from this learning workspace.
- Product branch remains under its existing Human Live League design-review authority. Teaching does not authorize implementation or reopen frozen studies.
