# PR Describe Bot

A GitHub App that reports GitHub Check Runs on a pull request for a small
set of checks, updating them as the PR changes. Built to demonstrate GitHub
App auth (JWT + installation tokens), webhook signature verification, and
idempotent reconciliation against an external API -- no database needed.

## Checks

- **`pr-describe-bot/description`** -- fails if the PR body is empty, or too
  short once any HTML-comment template boilerplate is stripped out.
- **`pr-describe-bot/pr-size`** -- fails if the diff changes more than 500
  lines (additions + deletions combined). Large PRs get reviewed less
  thoroughly; the summary suggests splitting it up.

Each is a separate named Check Run, so they report and update independently
-- a PR can fail one, both, or neither.

## How it works

1. GitHub delivers a `pull_request` webhook (`opened`/`edited`/`synchronize`/`reopened`) to `POST /webhook`.
2. The signature is verified (HMAC-SHA256) against the App's webhook secret.
3. The bot authenticates as the GitHub App (short-lived JWT -> installation access token) and evaluates both checks against the PR (the description and diff size are both already present on the webhook payload -- no extra API call needed to evaluate them).
4. For each check, it looks up an existing Check Run for the PR's current head commit by name; if one exists it's updated (new conclusion + summary), otherwise a new one is created. Nothing is ever deleted -- a check that starts failing and later passes just flips from `failure` to `success` on the same run.

## Local development

    python -m pip install -e ".[dev]"
    pytest tests/unit tests/integration -v
    make run

`GITHUB_APP_PRIVATE_KEY` is a multi-line PEM value. In a local `.env` file it
must be wrapped in quotes (e.g. `GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA
PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"`) so `pydantic-settings`
parses it as a single value -- otherwise it fails silently at startup and
only surfaces as an opaque parsing error on the first webhook delivery.

## Creating the GitHub App

1. GitHub -> Settings -> Developer settings -> GitHub Apps -> New GitHub App.
2. Webhook URL: your deployed `/webhook` URL. Generate and save a webhook secret.
3. Permissions: **Checks** (Read & write). `Metadata` (Read-only) is included by default.
4. Subscribe to events: Pull request.
5. Generate a private key (downloads a `.pem` file) -- paste its full contents into `GITHUB_APP_PRIVATE_KEY`.
6. Note the App ID (top of the app's settings page) -- goes into `GITHUB_APP_ID`.

If you're updating an existing installation from an earlier version of this
app (which used Pull Request comments instead of Check Runs), change the
App's permissions to grant `Checks: Read & write` -- GitHub will prompt each
installation's owner to approve the updated permission set before it takes
effect.

## Deploy (Render)

1. Render dashboard -> New -> Blueprint -> point at this repo (reads `render.yaml`).
2. Fill in `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`.
3. Once deployed, set the GitHub App's webhook URL to `https://<your-service>.onrender.com/webhook`.
4. Install the App on this repository (and any other) to see it in action on real PRs.
