# PR Describe Bot

A GitHub App that comments on a pull request when it fails one of a small
set of checks, and removes the comment once it's fixed. Built to demonstrate
GitHub App auth (JWT + installation tokens), webhook signature verification,
and idempotent reconciliation against an external API -- no database needed.

## Checks

- **Missing description** -- the PR body is empty, or too short once any
  HTML-comment template boilerplate is stripped out.
- **PR too large** -- the diff changes more than 500 lines (additions +
  deletions combined). Large PRs get reviewed less thoroughly; the comment
  suggests splitting it up.

Each check gets its own marker-tagged comment, so they don't interfere with
each other -- a PR can be nagged for both at once, or either independently.

## How it works

1. GitHub delivers a `pull_request` webhook (`opened`/`edited`/`synchronize`/`reopened`) to `POST /webhook`.
2. The signature is verified (HMAC-SHA256) against the App's webhook secret.
3. The bot authenticates as the GitHub App (short-lived JWT -> installation access token) and runs every check against the PR.
4. For each check that fails, it posts (or updates) that check's marker-tagged comment; for each that passes, it removes that comment if one exists. Only a comment actually authored by the bot (verified via the GitHub API's `user.type == "Bot"`) is ever touched -- a human quoting the bot's comment back can't accidentally have their own comment edited or deleted.

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
3. Permissions: Pull requests (Read & write), Metadata (Read-only).
4. Subscribe to events: Pull request.
5. Generate a private key (downloads a `.pem` file) -- paste its full contents into `GITHUB_APP_PRIVATE_KEY`.
6. Note the App ID (top of the app's settings page) -- goes into `GITHUB_APP_ID`.

## Deploy (Render)

1. Render dashboard -> New -> Blueprint -> point at this repo (reads `render.yaml`).
2. Fill in `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`.
3. Once deployed, set the GitHub App's webhook URL to `https://<your-service>.onrender.com/webhook`.
4. Install the App on this repository (and any other) to see it in action on real PRs.
