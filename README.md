# PR Describe Bot

A GitHub App that comments on a pull request when it's missing a description,
and removes the comment once one is added. Built to demonstrate GitHub App
auth (JWT + installation tokens), webhook signature verification, and
idempotent reconciliation against an external API -- no database needed.

## How it works

1. GitHub delivers a `pull_request` webhook (`opened`/`edited`/`synchronize`/`reopened`) to `POST /webhook`.
2. The signature is verified (HMAC-SHA256) against the App's webhook secret.
3. The bot authenticates as the GitHub App (short-lived JWT -> installation access token) and checks the PR body.
4. If the description is missing, it posts (or updates) a single marker-tagged comment on the PR. Once a real description is added, that comment is removed.

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
