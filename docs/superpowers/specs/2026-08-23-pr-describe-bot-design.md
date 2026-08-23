# PR Describe Bot — Design

**Goal:** A public GitHub App that comments on a pull request when it's missing a description, and keeps that comment in sync (updates or removes it) as the PR is edited. Built as a portfolio piece demonstrating GitHub App auth, webhook handling, and a real dev-tool product shape.

## Context

Standalone portfolio project, built solo, following a brainstorm → spec → plan → implementation workflow. Target audience: anyone browsing the author's GitHub profile, plus (secondarily) real GitHub users who might install the app.

## Architecture

A single FastAPI backend, no frontend and no database for v1:

- **GitHub App** registered on GitHub, with `pull_request` webhook events subscribed (`opened`, `edited`, `synchronize`, `reopened`) and permissions: Pull requests (read & write), Metadata (read-only).
- **`POST /webhook`** endpoint: verifies the `X-Hub-Signature-256` header (HMAC-SHA256 over the raw body using the App's webhook secret), reads `X-GitHub-Event`, and for `pull_request` events with an actionable `action`, runs the description check and syncs the bot's comment.
- **No database.** Every check re-reads the current PR state from the GitHub API on each webhook delivery — there's nothing to persist for a single stateless check. (A future check that needs history, e.g. "flag PRs open more than N days," would need to change this; out of scope for v1.)
- **Auth to the GitHub API**: the App's private key (PEM, stored as an env var) signs a short-lived JWT identifying the App; that JWT is exchanged for an installation access token (using the `installation.id` present in every webhook payload) via GitHub's `POST /app/installations/{id}/access_tokens`. Installation tokens are requested per-request (no caching) for v1 — they're valid 1 hour, cheap to request, and caching adds state/complexity for no measurable benefit at this traffic scale.
- **Every outgoing GitHub API request sends `X-GitHub-Api-Version: 2022-11-28`.** GitHub versions its REST API by date and defaults to the account's configured version if the header is omitted — pinning it explicitly means a GitHub-side default change can never silently alter this app's behavior.

## Concurrency

GitHub can deliver `opened` and a near-simultaneous `synchronize` (e.g. a PR opened from a branch that immediately gets an auto-push) as two overlapping webhook requests for the same PR. Without serialization, both handlers could list "no marker comment yet" before either has created one, and both create it — two nag comments on the same PR.

Fixed with an in-process `asyncio.Lock` keyed by `(repository_full_name, pr_number)`: the reconcile step (list comments → decide → act) runs inside that lock, so a second concurrent webhook for the same PR waits for the first to finish before it lists comments, and sees the already-created/updated/deleted state. This only serializes within a single running process — correct for v1's single Render instance. Running more than one instance would reopen the race and need a real distributed lock (e.g. a Postgres advisory lock or Redis); explicitly out of scope until there's a reason to run more than one instance.

## The v1 check: missing description

- **Trigger:** on `opened`, `edited`, `synchronize`, `reopened`.
- **Rule:** the PR body is "missing" if it's `None`/empty, or — after stripping whitespace and any HTML comments — shorter than 20 characters. (HTML comments are stripped before the length check because GitHub's default PR template text lives inside them and shouldn't count as a real description.)
- **If missing:** post a comment asking for a description, OR update the existing bot comment if one is already present (idempotent — never post a second nag comment on the same PR).
- **If present (no longer missing):** if a bot comment exists from a previous "missing" state, delete it — the PR is fixed, the nag should go away.
- **Finding the bot's own comment:** every comment the bot posts includes an invisible HTML-comment marker (`<!-- pr-describe-bot:marker -->`) at the end of its body. To find "the bot's comment on this PR," list the PR's issue comments via the GitHub API and find the one whose body contains that marker — this works even before the bot's own GitHub identity (login) is known at request-signing time in tests, and doesn't depend on comparing user IDs.

## Data flow

1. GitHub delivers a `pull_request` webhook to `POST /webhook`.
2. Signature verified against the raw body; request rejected (401) if invalid.
3. Event payload parsed: `action`, `installation.id`, `pull_request.number`, `pull_request.body`, `repository.full_name`.
4. If `action` isn't one of the four handled ones, respond 200 immediately (no-op) — GitHub expects a fast 2xx even for events we ignore, to avoid being flagged as an unreliable webhook endpoint.
5. Exchange the App JWT + `installation.id` for an installation access token.
6. Evaluate the description rule against `pull_request.body`.
7. List existing PR comments, find the bot's marker comment (if any).
8. Reconcile: create / update / delete / no-op, using the installation token.

## Error handling

- Invalid webhook signature → 401, no GitHub API calls made.
- GitHub API call fails (rate limit, 5xx, network) → log the error, return 500 so GitHub's webhook delivery UI shows the failure (GitHub retries failed deliveries automatically); never silently swallow a failed comment sync.
- Malformed/unexpected payload shape (missing expected fields) → return 400, log the payload's `action` and delivery ID for debugging.

## Testing

- Unit: signature verification (valid/invalid/missing header), the description-missing rule (empty, whitespace-only, short, long-enough, HTML-comment-only body), the reconcile decision logic (create/update/delete/no-op) against a faked "existing comment or not" state.
- Integration: `POST /webhook` end-to-end with a real example GitHub payload fixture, GitHub API calls mocked (no real network calls in tests) — covering signature rejection, an ignored action, and each reconcile outcome.
- Concurrency: two overlapping webhook requests for the same `(repo, pr_number)` (started together, e.g. via `asyncio.gather`) result in exactly one marker comment being created, not two.

## Deployment

Render web service (Docker): `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET` as Render secrets. No database service needed. The GitHub App's "Homepage URL" can point at the GitHub repo itself for v1 — no landing page needed to ship the working bot.

## Dogfooding

Once deployed, the App gets installed on its own repository. Every PR opened against `pr-describe-bot` itself is then checked by the bot it contains — a working, permanently up-to-date live demo, visible on any PR in the repo's own history without a separate demo environment or screen recording.

## Out of scope for v1

- Any check other than "missing description" (large-diff warning, TODO detection, missing-tests heuristic) — explicitly deferred; the reconcile-by-marker-comment pattern here is written to be reusable per-check later, but no multi-check abstraction is built until a second check actually exists.
- A marketing/landing page for the GitHub App listing.
- Caching installation tokens.
- Any persistence layer.
