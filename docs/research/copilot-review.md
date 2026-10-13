# Copilot PR review automation via `gh`

Research for issue [#5](https://github.com/Bezoar/pdf2epub/issues/5). Researched 2026-10-13 against
docs.github.com, the GitHub changelog, the REST OpenAPI description, live GraphQL introspection,
`gh` 2.101.0, and Copilot reviews on public PRs. GitHub changes this feature often, so re-check the
open gaps before relying on them.

## TL;DR

- **"Lite" is a Copilot code review *effort level*.** It is not a model or a plan tier. The two
  levels are **Lite** and **Balanced**. They were called Low and Medium in preview and went GA on
  2026-08-07. Balanced has been the default since 2026-09-28.
  ([changelog 08-07](https://github.blog/changelog/2026-08-07-copilot-code-review-effort-levels-are-generally-available/),
  [changelog 10-02](https://github.blog/changelog/2026-10-02-copilot-code-review-api-support-and-new-default-effort-level/))
- **You can't choose Lite per request from `gh` or the API yet, as far as I can verify.** The 10-02
  changelog says the REST and GraphQL APIs accept an optional effort level, but neither the REST
  schema nor live GraphQL introspection has the field (see Open gaps). **Workaround:** set the owner's
  **personal** default effort to Lite. That default applies to every review the owner requests,
  including reviews requested through `gh`. Each review's overview comment prints
  `Review effort: Lite|Balanced`, so the agent can check which level ran.
- **Request or re-request a review:** `gh pr edit <N> --add-reviewer @copilot`.
- **Severity:** Copilot uses three levels: **High / Medium / Low**. There is no Critical. Severity
  appears only in the review's *overview* body, not in the inline comment bodies.
- **Auto-merge:** `gh pr merge <N> --auto --squash`. With no required checks or reviews, this
  **merges immediately**. Copilot's review is a non-blocking "Comment" review, so the agent's
  3-round loop is the actual gate, not GitHub.
- **Repo state today:** `allow_auto_merge=false`, `main` unprotected, no rulesets. The owner must
  configure the Copilot effort settings in the web UI. No API for them is documented.

## 1. What "Lite" is

| Item | Finding | Source |
|---|---|---|
| Meaning | An effort level. Lite is a "cost-efficient review that provides targeted feedback on glaring issues such as bugs, security vulnerabilities, and style inconsistencies". Balanced routes to "a higher-reasoning model". | [use-code-review](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/request-a-code-review/use-code-review), [about code review](https://docs.github.com/en/copilot/concepts/agents/code-review) |
| Names | Preview "Low"/"Medium" were renamed Lite/Balanced. | [changelog 08-07](https://github.blog/changelog/2026-08-07-copilot-code-review-effort-levels-are-generally-available/) |
| Default | Balanced since 2026-09-28. An explicit Lite selection is kept. | [changelog 10-02](https://github.blog/changelog/2026-10-02-copilot-code-review-api-support-and-new-default-effort-level/) |
| Implementation | Lite uses "an ensemble of agents" whose findings are merged into one review. | [changelog 09-11](https://github.blog/changelog/2026-09-11-auto-resolution-and-analysis-updates-in-copilot-code-review/) |
| Model choice | "Model switching is not supported". | [about code review](https://docs.github.com/en/copilot/concepts/agents/code-review) |
| Cost | Lite: about $0.05 to $1 of AI credits per review. Balanced: about $0.25 to $5. | [about code review](https://docs.github.com/en/copilot/concepts/agents/code-review) |
| "Max" | Appears in personal settings marked "Coming soon". | [configure-code-review](https://docs.github.com/en/copilot/how-tos/copilot-on-github/set-up-copilot/configure-code-review) |
| Plans | Lite and Balanced are available on Copilot Pro, Pro+, Max, Business, and Enterprise. | [changelog 08-07](https://github.blog/changelog/2026-08-07-copilot-code-review-effort-levels-are-generally-available/) |

**Where to set Lite** ([configure-code-review](https://docs.github.com/en/copilot/how-tos/copilot-on-github/set-up-copilot/configure-code-review)):

- **Personal** (this is what governs reviews the owner requests through `gh`): profile menu → Copilot
  settings → Code review → "Review effort level" = **Lite**. It "applies to reviews you request,
  including automatic ones"
  ([changelog 09-23](https://github.blog/changelog/2026-09-23-copilot-code-review-more-ways-to-request-and-configure-reviews/)).
- **Repository:** Settings → Copilot → Code review → "Review effort level". The docs describe this as
  the level for *automatic* reviews in the repo.
- **Per request in the UI:** the Reviewers menu offers an effort choice before you request a review.

## 2. Commands and API calls

Variables: `R=Bezoar/pdf2epub`, `N=<pr number>`.

### 2.1 Request a review

```bash
gh pr create --reviewer @copilot ...          # request at creation
gh pr edit "$N" --add-reviewer @copilot        # request on an existing PR
```

Both forms come from [use-code-review](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/request-a-code-review/use-code-review).
`gh pr edit --help` (2.101.0) documents `@copilot` as a special value of `--add-reviewer`.

Raw API equivalents:

- REST: `POST /repos/{owner}/{repo}/pulls/{n}/requested_reviewers` with
  `reviewers: ["copilot-pull-request-reviewer[bot]"]`. The docs say to "request
  `copilot-pull-request-reviewer[bot]` as a reviewer"
  ([use-code-review](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/request-a-code-review/use-code-review),
  [REST review-requests](https://docs.github.com/en/rest/pulls/review-requests)).
- GraphQL: `requestReviewsByLogin(input:{pullRequestId, botLogins:["copilot-pull-request-reviewer[bot]"], union:true})`.
  Live introspection describes `botLogins` as "including the [bot] suffix (e.g.,
  'copilot-pull-request-reviewer[bot]')".

### 2.2 Wait for the review to finish (poll for up to 30 minutes)

A review is done when a new review by `copilot-pull-request-reviewer[bot]` appears with
`submitted_at` later than the time you requested it. A submitted reviewer is also removed from
`requested_reviewers`
([REST review-requests](https://docs.github.com/en/rest/pulls/review-requests)). The docs give no
explicit completion signal and say a review "usually takes less than 30 seconds"
([use-code-review](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/request-a-code-review/use-code-review)).
In practice, the Balanced reviews observed on
[openvinotoolkit/openvino.genai#4613](https://github.com/openvinotoolkit/openvino.genai/pull/4613)
took about 3.5 to 4 minutes from `review_requested` to `reviewed` in the issue timeline.

```bash
T0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gh pr edit "$N" --add-reviewer @copilot
for i in $(seq 1 60); do                       # 60 x 30 s = 30 min
  REVIEW=$(gh api "repos/$R/pulls/$N/reviews" --paginate \
    --jq "[.[] | select(.user.login==\"copilot-pull-request-reviewer[bot]\" and .submitted_at > \"$T0\")] | last")
  [ "$REVIEW" != "null" ] && [ -n "$REVIEW" ] && break
  sleep 30
done
# Still empty after 60 iterations: timeout. Escalate to the owner.
```

**Failure mode seen in practice.** When the requester is out of AI credits, Copilot still submits a
`COMMENTED` review whose body is "Copilot was unable to review this pull request because the user who
requested the review has reached their quota limit."
(seen on [Tiesol/rondo#118](https://github.com/Tiesol/rondo/pull/118) and
[sQVe/tau#347](https://github.com/sQVe/tau/pull/347)). The docs also say "code reviews are blocked
when the user reaches their budget"
([about code review](https://docs.github.com/en/copilot/concepts/agents/code-review)). Check the body
for `unable to review`, and escalate if it's there rather than treating the PR as clean.

### 2.3 Fetch the review and its comments

```bash
# Overview body: verdict, effort level, open findings with severity
echo "$REVIEW" | jq -r .body
REVIEW_ID=$(echo "$REVIEW" | jq .id)

# Inline comments from this review (no severity inside them)
gh api "repos/$R/pulls/$N/reviews/$REVIEW_ID/comments" --paginate

# Unresolved Copilot threads, so the agent can reply and resolve them
gh api graphql -F owner=Bezoar -F name=pdf2epub -F n="$N" -f query='
query($owner:String!,$name:String!,$n:Int!){ repository(owner:$owner,name:$name){
  pullRequest(number:$n){ reviewThreads(first:100){ nodes{ id isResolved path line
    comments(first:1){ nodes{ databaseId author{login} body url } } } } } } }'
```

The endpoints are documented at [REST pull request reviews](https://docs.github.com/en/rest/pulls/reviews)
and [REST review comments](https://docs.github.com/en/rest/pulls/comments). After fixing a finding, the
agent can close the thread with GraphQL `resolveReviewThread(input:{threadId})`. Copilot also resolves
its own threads on re-review when a later commit addresses them
([changelog 09-11](https://github.blog/changelog/2026-09-11-auto-resolution-and-analysis-updates-in-copilot-code-review/)).
In the UI, the "Resolve conversation" dropdown offers Addressed, Won't fix, and Incorrect
([changelog 08-27](https://github.blog/changelog/2026-08-27-copilot-code-review-resolution-reasons-and-expanded-capabilities/)).

### 2.4 Re-request a review after fixes

```bash
git push && T0=$(date -u +%Y-%m-%dT%H:%M:%SZ) && gh pr edit "$N" --add-reviewer @copilot
```

`gh pr edit --help` says `--add-reviewer` adds "or re-request[s]" reviewers. The UI equivalent is the
re-request button next to Copilot's name. If automatic review is configured with "Review new pushes",
Copilot re-reviews each push on its own. Without that option, "Copilot will only review the pull
request once"
([configure-code-review](https://docs.github.com/en/copilot/how-tos/copilot-on-github/set-up-copilot/configure-code-review)).
Use one mechanism, not both: an explicit request is easier to correlate with `T0`, so leave
"Review new pushes" **off**. The docs warn that Copilot "may repeat comments that were previously
resolved or downvoted"
([use-code-review](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/request-a-code-review/use-code-review)).

### 2.5 Merge

```bash
gh pr merge "$N" --auto --squash --delete-branch --match-head-commit "$(git rev-parse HEAD)"
```

- How `gh` handles `--auto`
  ([cli source, merge.go](https://github.com/cli/cli/blob/trunk/pkg/cmd/pr/merge/merge.go)):
  `autoMerge: opts.AutoMergeEnable && !isImmediatelyMergeable(pr.MergeStateStatus)`.
  For `CLEAN`, `HAS_HOOKS`, and `UNSTABLE` (failing *non-required* checks), gh **merges immediately**
  and ignores `--auto`. Non-interactive use also needs an explicit `--squash`, `--merge`, or `--rebase`.
- GitHub offers auto-merge only "on pull requests that cannot be merged immediately", and the repo
  setting must be on
  ([automatically-merging](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request),
  [managing auto-merge](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-auto-merge-for-pull-requests-in-your-repository)).
  The repo field is `allow_auto_merge` on `PATCH /repos/{owner}/{repo}` (REST OpenAPI description).
- Copilot's review is a "Comment" review and "do[es] not count toward required approvals". Approving
  reviews are a public-preview option that is off by default
  ([use-code-review](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/request-a-code-review/use-code-review)).
  GitHub therefore never blocks a merge on Copilot's feedback. The agent's severity check is the only
  gate.
- `--match-head-commit` makes sure the reviewed SHA is the one that gets merged.

## 3. Prerequisites and current repo state

| Prerequisite | Needed for | Status (checked 2026-10-13, read-only) |
|---|---|---|
| Copilot plan with code review (Pro, Pro+, Max, Business, or Enterprise) | Any review; Lite | Unknown. No documented API exposes a personal Copilot entitlement. **Owner to confirm.** |
| AI-credit budget | Each review (about $0.05 to $1 for Lite) | Unknown. Running out produces the "unable to review" body (§2.2). |
| Personal effort default = Lite | Lite for reviews requested through `gh` | Unknown. UI-only. **Owner to set.** |
| Repo effort default = Lite | Lite for automatic reviews (optional) | Unknown. UI-only. |
| `allow_auto_merge` | Real auto-merge when requirements are pending | `false` (`gh api repos/Bezoar/pdf2epub`) |
| Auto-merge on a private repo | Needs a paid plan (Pro, Team, or Enterprise) | Per [gated-features/auto-merge](https://github.com/github/docs/blob/main/data/reusables/gated-features/auto-merge.md). The owner's plan isn't visible (`.plan` is null without the `user` scope). |
| Branch protection or ruleset on `main` | Required checks, which make `--auto` meaningful | None. `GET .../branches/main/protection` returns 404 "Branch not protected", and `GET .../rulesets` returns `[]`. Rulesets on private repos need Pro, Team, or Enterprise ([gated-features/repo-rules](https://github.com/github/docs/blob/main/data/reusables/gated-features/repo-rules.md)). Inference: a 404 rather than a plan-gate error suggests the account can use protection on this private repo. Unverified. |
| `delete_branch_on_merge` | Tidiness | `false`. Use `--delete-branch` instead. |
| Merge methods | `--squash` | squash, merge, and rebase are all allowed |

**Automatic review (optional, not recommended for this loop).** Add a branch ruleset with the rule
"Automatically request Copilot code review". Its REST rule type is `copilot_code_review` with
parameters `review_on_push` and `review_draft_pull_requests`, and **it has no effort parameter**
(REST OpenAPI `repository-rule-copilot-code-review`;
[configure-code-review](https://docs.github.com/en/copilot/how-tos/copilot-on-github/set-up-copilot/configure-code-review)).

## 4. Classifying severity

**Documented:** "Copilot labels each comment with a severity level of "High," "Medium," or "Low""
([use-code-review](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/request-a-code-review/use-code-review)).
Copilot has **no CRITICAL level**.

**Where severity appears (observed, not documented).** The review *overview body* begins with the
marker `<!-- ccr-overview-v2 -->` and contains the following:

- A verdict heading. Observed values: `### 🟢 Approval recommended`, `### 🔵 Needs a closer look`,
  and `### 🟡 Changes recommended`
  ([RbBtSn0w/adg#125](https://github.com/RbBtSn0w/adg/pull/125),
  [openvinotoolkit/openvino.genai#4613](https://github.com/openvinotoolkit/openvino.genai/pull/4613)).
- `<summary><strong>N open findings</strong></summary>`, followed by one list item per finding. Each
  item has an `<img alt="High severity">` (or Medium or Low) and a link to `#discussion_r<commentId>`.
- Optional sections: `N resolved since last review` and `Previously missed (N)` (findings in
  unchanged code).
- A line with `🧠 **Review effort:** Lite` or `Balanced`.

The inline comment bodies themselves had **no** severity text
([microsoft/vscode#340825](https://github.com/microsoft/vscode/pull/340825)).

**Classification rule for the loop:**

1. Use the latest Copilot review whose `submitted_at` is later than `T0`. Its body must not contain
   `unable to review`.
2. Count severities in the "open findings" and "Previously missed" sections only. Skip "resolved
   since last review".
   ```bash
   echo "$REVIEW" | jq -r .body \
     | awk '/resolved since last review/{skip=1} /open finding|Previously missed/{skip=0} !skip' \
     | grep -oE '(High|Medium|Low) severity' | sort | uniq -c
   ```
3. Map High to HIGH and Medium to MEDIUM. Treat the owner's "CRITICAL" as High, since Copilot never
   emits Critical. **Blocking** means any open High or Medium finding.
4. **Fail closed.** If the marker `ccr-overview-v2` is missing, or the body can't be parsed, but
   unresolved Copilot threads exist, treat the PR as blocking and escalate.

## 5. The loop (as proposed)

```
round = 0
request review (T0) → poll ≤30 min ─ timeout / "unable to review" ─→ ESCALATE
           │
           ▼
     classify open findings
           │
   any High/Medium? ──no──→ address/resolve Low (optional) → gh pr merge --auto --squash → done
           │yes
   round < 3 ? ──no──→ ESCALATE (comment on PR, tag @Bezoar, leave open)
           │yes
   fix, reply/resolve threads, push, round++, re-request (new T0) ─┘
```

## 6. Open gaps

1. **Per-request effort through the API or CLI.** The [10-02 changelog](https://github.blog/changelog/2026-10-02-copilot-code-review-api-support-and-new-default-effort-level/)
   says an effort level "can optionally" be set on API requests. On 2026-10-13, however, the REST
   `requested_reviewers` body in the published OpenAPI description has only `reviewers` and
   `team_reviewers`. GraphQL `RequestReviewsInput`, `RequestReviewsByLoginInput`, and
   `RerequestReviewsInput` have no effort field, and no input type in the schema has a field matching
   `effort`. `gh pr edit` has no effort flag. Until one ships, use the personal Lite default, and
   check `Review effort:` in the overview.
2. **The overview format is undocumented.** The `ccr-overview-v2` markup, the verdict headings, and the
   `alt="… severity"` labels were observed, not specified, and may change. The parser must fail
   closed.
3. **Completion signal.** No documented "review complete" event or status exists. Polling the reviews
   list is the only method. The observed latency of minutes contradicts the documented "<30 seconds".
4. **Owner's Copilot plan and remaining credits** can't be read through a documented API.
5. **The Copilot settings pages** (effort defaults) have no documented API. They must be set by hand
   in the UI.
6. **Not tested end-to-end on this repo.** No PR was opened. The first real PR should confirm
   `--add-reviewer @copilot` on a private repo and confirm that the overview shows `Review effort: Lite`.

## 7. Draft for `docs/instructions/github.md`

```markdown
## PR review loop (GitHub Copilot)

One-time owner setup (UI only):
- Profile → Copilot settings → Code review → Review effort level = **Lite**.
- Leave "Automatic Copilot code review" / "Review new pushes" **off**; the agent requests reviews.
- Optional: Settings → General → Allow auto-merge; add a ruleset requiring CI checks on `main`.

Per PR (R=Bezoar/pdf2epub, N=PR number), max 3 rounds:
1. `T0=$(date -u +%Y-%m-%dT%H:%M:%SZ); gh pr edit $N --add-reviewer @copilot`
2. Poll every 30 s for ≤30 min:
   `gh api repos/$R/pulls/$N/reviews --paginate --jq '[.[]|select(.user.login=="copilot-pull-request-reviewer[bot]" and .submitted_at>"'$T0'")]|last'`
   - Timeout, or body contains "unable to review" → escalate to @Bezoar, stop.
3. Read the review body. Confirm "Review effort:** Lite". Count `High|Medium|Low severity` in the
   "open findings" + "Previously missed" sections (ignore "resolved since last review").
   Copilot has no Critical level; High is the top.
4. No open High/Medium → `gh pr merge $N --auto --squash --delete-branch --match-head-commit <sha>`.
   (With no required checks this merges immediately.)
5. Otherwise fix every High/Medium finding (Low at discretion), reply on and resolve each thread
   (`resolveReviewThread`), push, and go to 1.
6. After round 3, if any High/Medium remains: leave the PR open, comment a summary of the
   outstanding findings tagging @Bezoar, and stop.
Fail closed: if the review body can't be parsed but unresolved Copilot threads exist, escalate.
```
