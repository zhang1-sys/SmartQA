# SmartQA Hosting Risk Plan

## Current State

- Current online backend: Render Free web service.
- Render Free is acceptable for a portfolio/interview-ready staging system, but it is not the final enterprise production target.
- Known risks:
  - cold starts can delay first response and WeCom callback handling.
  - long Dify calls can approach request timeout.
  - in-process background threads are best-effort and depend on the web worker staying alive.
  - autosleep can delay retry scheduler and customer-service poller runs.

## Near-Term Controls

- Keep WeCom KF manual sync available for recovery.
- Keep message delivery retry scheduler enabled, but verify its `message_delivery_retry` runtime state after each deploy.
- Keep Dify smoke tests short for release checks and run the 24-case regression set only before important demos or overnight.
- Treat `APP_ENV=staging` on Render as the expected low-cost deployment mode.

## Recommended Upgrade Path

1. Move to a paid always-on Render instance or a small cloud VM.
2. Split background workers from the web process:
   - WeCom KF poller
   - failed delivery retry scheduler
   - knowledge sync retry jobs
3. Add uptime monitoring against `/api/system/health`.
4. Add a scheduled production smoke that checks:
   - WeCom token health
   - Dify workflow call
   - Supabase health
   - failed delivery count
   - stale Dify document count

## What Not To Change Yet

- Do not add role separation now. The current phase intentionally keeps one administrator account.
- Do not move secrets into committed files.
