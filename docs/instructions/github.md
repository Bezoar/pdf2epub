# GitHub instructions

How work moves from a ticket to `main` in `Bezoar/pdf2epub`. These are instructions, not specification. "Must" and "must not" are binding. In commands, `R=Bezoar/pdf2epub`, `N` is the PR number and `NNN` is the ticket number.

## 1. One-time owner setup

The agent can't do these steps; the owner (@Bezoar) does them once, in the web UI.

- [ ] Personal Copilot settings → Code review → **Review effort level = Lite**.
- [ ] Repo Settings → Copilot → Code review → **Review effort level = Lite**. Setting both is the most robust option, because defaults cascade enterprise → org → repo → personal.
- [ ] "Automatic Copilot code review" and "Review new pushes" stay **off**; the agent requests reviews itself.
- [ ] Repo Settings → Copilot → Code review → **Auto-approval** (public preview, off by default):
  - turn on **Allow Copilot to approve pull requests**;
  - turn on **Allow Copilot approvals to count toward merge requirements**;
  - leave **File paths** blank, so approvals count for every file.

  The repo is user-owned, so there are no organisation or enterprise levels to set.
- [ ] The `needs-owner` label exists (`gh label create needs-owner --color B60205` if not).
- [ ] `.github/CODEOWNERS` (`* @Bezoar`) lands in ticket 0. Until then, the code-owner rule has nothing to resolve.

Already applied (for reference): squash merges only, delete branch on merge, auto-merge allowed; rulesets `main-protection` (1 approval, code-owner review, no force-push or deletion; Admin bypass) and `restrict-branch-pushes`; fork-PR Actions need approval; secret scanning, push protection and Dependabot alerts on.

## 2. Starting a ticket

1. Only work on a ticket labelled `ready-for-agent`, unless the owner tells you otherwise.
2. Assign it to yourself before any other work: `gh issue edit NNN --add-assignee @me`. An assigned ticket is claimed; skip tickets someone else holds.
3. Read the ticket's ACs and follow each link to the spec text. The spec is normative; the ticket's short descriptions are not.
4. Branch from an up-to-date `main`: `git switch main && git pull && git switch -c NNN-short-slug`.
5. If the ticket is labelled `hitl`, work with the owner in the session. It is never merged by the agent (see [§5](#5-escalation)).

## 3. Commits and the pull request

1. Commit messages use **Conventional Commits**: `feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `build:`, `ci:`, `chore:`. Keep the summary line ≤ 72 characters.
2. One PR per ticket. Every PR must have a ticket, except Dependabot's.
3. PR title: `[#NNN] <plain title>`, the ticket's title in plain text. Squash-merging uses it as the commit title.
4. The PR body must follow [`.github/pull_request_template.md`](../../.github/pull_request_template.md). That template is the single source for the body's sections: `Closes #NNN`, each AC ID with its marked tests, **Spec changes**, new runtime dependencies, coverage pragmas, and the review-effort note.
5. Open the PR with `gh pr create --base main --title "[#NNN] <title>" --body-file <file>`.

## 4. The per-PR loop

Run these steps in order. A **round** is one Copilot review request. There are at most 3 rounds.

1. **Tick ACs.** On the ticket, tick each AC checkbox once its marked test is green.
2. **Green CI first.** Push, then wait for CI: `gh pr checks N --watch`. In v1, CI isn't a required check, so this step is your gate.
   - If CI is red, fix it and push again before any review round.
   - If CI is still red after 3 fix attempts, escalate ([§5](#5-escalation)).
3. **Request a review.**
   ```sh
   T0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
   gh pr edit N --add-reviewer @copilot
   ```
4. **Wait for it.** Poll every 30 s, for at most 30 minutes:
   ```sh
   gh api repos/$R/pulls/N/reviews --paginate \
     --jq '[.[] | select(.user.login=="copilot-pull-request-reviewer[bot]" and .submitted_at > "'"$T0"'")] | last'
   ```
   Escalate if it times out, or if the review body says Copilot is unable to review.
5. **Read the review.**
   - Check the review body's `Review effort:` line. If it isn't `Lite`, carry on, and add a note to the PR body under the template's review-effort section.
   - Count the findings marked `High`, `Medium` or `Low` severity in the open-findings and "previously missed" sections. Ignore the "resolved since last review" section.
   - Copilot has no Critical level; High is the highest.
   - Read the review's **approval assessment** in the overview, and its review state: `APPROVED` means Copilot approved; `COMMENTED` means it didn't.
   - If the review body can't be parsed but unresolved Copilot threads exist, escalate (fail closed).
   - If Copilot approved but the review still lists an open High or Medium finding, treat it as unparseable and escalate (fail closed).
6. **Act on findings.**
   - **High and Medium:** you must fix every one.
   - **Low:** fix it if the fix is small. Otherwise reply in the thread with a one-line reason.
   - **Reply inline, one thread at a time.** Answer each finding by replying in its own review thread, stating its disposition:
     - `Fixed in <short-sha>: <what changed>`;
     - `Won't fix (Low): <one-line reason>`;
     - `Disputed: <reasoning>`.

     Use `gh api repos/$R/pulls/N/comments/<comment-id>/replies -f body='…'`, where `<comment-id>` is the thread's first comment. You must not post a separate PR comment listing the changes instead.
   - Resolve each thread you fixed or answered (GraphQL `resolveReviewThread`). Leave disputed threads open.
   - **Disputed High or Medium:** if you believe one is wrong, reply with your reasoning and leave the thread **unresolved**. You must not dismiss it yourself; escalate after this round.
7. **Next round, or stop.**
   - If you pushed fixes, wait for green CI on the new head (step 2) and start the next round (step 3).
   - If High or Medium findings remain after round 3, escalate.
8. **Merge.** Merge only when all of these are true:
   - CI is green on the exact head commit;
   - no High or Medium finding is open or disputed;
   - the ticket isn't `hitl`.

   Copilot's approval is **not** part of this gate. If it didn't approve but no High or Medium finding remains, still merge, and note the assessment in the PR body under the template's review-effort section.

   Merge in this order:
   1. If Copilot's latest review is `APPROVED` **on the head commit** (a new push dismisses its approval), try a normal merge first:
      ```sh
      gh pr merge N --squash --delete-branch --match-head-commit <head-sha>
      ```
   2. If that is refused (the ruleset's code-owner review isn't satisfied, because Copilot isn't in `CODEOWNERS`), or Copilot didn't approve, merge through admin bypass:
      ```sh
      gh pr merge N --squash --admin --delete-branch --match-head-commit <head-sha>
      ```

   You must not use `--auto`. Note in the PR's final comment which path merged it.
9. **After merging:** check that the ticket closed (via `Closes #NNN`), then pull `main`.

## 5. Escalation

Escalating always means the same thing:

1. Leave the PR open. Do not merge.
2. Add the label: `gh pr edit N --add-label needs-owner`.
3. Post **one** comment that tags @Bezoar, states the trigger, and lists the outstanding items (finding links, failing checks, or the requirement at stake).
4. Stop the session.

Triggers:

- High or Medium findings remain after round 3.
- A High or Medium finding is disputed.
- Copilot times out after 30 minutes, says it is unable to review, or its review can't be parsed.
- A change would alter the meaning of an existing spec requirement or AC ([coding.md §8](coding.md#8-spec-gaps)).
- A test is needed at a seam outside the plan's seam catalogue ([coding.md §3](coding.md#3-red-green-cycle)).
- A dependency that isn't MIT-compatible would be added ([coding.md §9](coding.md#9-dependencies)).
- The ticket is labelled `hitl`.
- CI is still red after 3 fix attempts.

## 6. Dependabot

- Dependabot PRs need no ticket and skip the Copilot loop.
- **The owner merges them.** The agent must not merge, approve or rebase a Dependabot PR unless the owner asks in the session.

## 7. Releases

1. The agent makes a commit `build: release version X.Y.Z` that bumps the version in `pyproject.toml`, on a branch with a release ticket, through the normal PR loop.
2. After merging, the agent builds and checks on a clean `main` checkout:
   ```sh
   uv build
   uvx twine check dist/*
   ```
3. Then the agent **stops** and reports the artefacts to the owner. Only the owner uploads to PyPI. Before the very first upload, the agent confirms the package metadata with the owner.
4. The agent must never handle, store or ask for PyPI tokens.
