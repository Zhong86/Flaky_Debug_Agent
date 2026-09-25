# GitHub Webhooks - Express Example

Minimal example of receiving GitHub webhooks with signature verification.

## Prerequisites

- Node.js 18+
- GitHub repository with webhook configured

## Setup

1. Install dependencies:
   ```bash
   npm install
   ```

2. Copy environment variables:
   ```bash
   cp .env.example .env
   ```

3. Add your GitHub webhook secret to `.env`

## Run

```bash
npm start
```

Server runs on http://localhost:3000

## Test

### Using Hookdeck CLI

```bash
# Forward webhooks to localhost
npx hookdeck-cli listen 3000 github --path /webhooks/github
```

Then configure the Hookdeck URL in your GitHub repository webhook settings.

### Trigger Test Events

- Push commits to your repository
- Create/close issues or pull requests
- GitHub will also send a `ping` event when you create the webhook

## Endpoint

- `POST /webhooks/github` - Receives and verifies GitHub webhook events
