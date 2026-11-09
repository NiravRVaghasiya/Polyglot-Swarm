# Launch checklist (go / no-go)

Work through this list before real learners use a deployment. Every
engineering item can be checked by a command or a CI run. The **operator
and legal** items cannot be settled by code: they need a decision by
whoever runs the service, and some need qualified counsel. A deployment
is ready for the public only when every line is ticked or explicitly
accepted in writing, with a name and date.

Related: [readiness audit](readiness-audit.md) (risk register),
[operations runbook](operations-runbook.md),
[security and privacy review](security-privacy-review.md),
[privacy notice template](../legal/privacy-notice-template.md).

## 1. Engineering (verified by CI or a command)

| ✓ | Item | How to check |
|---|---|---|
| ☐ | CI is green on the commit you deploy: tests, lint, types, secret scan, pip-audit, npm audit, container rehearsal (including the off-host restore drill) | the commit's checks on GitHub |
| ☐ | `.env.production` is filled in from `.env.production.example` and passes validation | `docker compose -f docker-compose.prod.yml run --rm api polyglot ops config-check` |
| ☐ | A TLS reverse proxy (Caddy, nginx, a cloud load balancer) is the only public entry point; the API listens on `127.0.0.1:8000` | `curl -I https://<your-domain>/health`; nothing else answers on the host's public IP |
| ☐ | `CORS_ORIGINS` and the web app's `NEXT_PUBLIC_API_URL` point at the public HTTPS addresses | the web app logs in and chats |
| ☐ | Off-host backups work: at least one `offsite: copy ok` in the log and a snapshot listed | `docker compose -f docker-compose.prod.yml logs offsite`; `... run --rm offsite snapshots` |
| ☐ | `RESTIC_PASSWORD` is stored outside the host (password manager) | without it the off-host copies cannot be decrypted |
| ☐ | One off-host restore drill done on staging | runbook, [Off-host copies](operations-runbook.md#off-host-copies) |
| ☐ | Prometheus scrapes `/metrics` with `METRICS_TOKEN`; `ops/prometheus/alerts.yml` is loaded and alerts reach a person | trigger a test alert |
| ☐ | Budgets fit what you are willing to spend: `LLM_GLOBAL_DAILY_BUDGET_USD`, `LLM_USER_DAILY_BUDGET_USD` | `.env.production` |
| ☐ | The host's disk is encrypted at rest (the local backup sets are not encrypted by the application) | your provider's volume settings |

## 2. Operator decisions

| ✓ | Decision | Notes |
|---|---|---|
| ☐ | **Who may use the service**, and whether **minors** are admitted | There is no age check in the product. If minors are excluded, say so in the privacy notice and terms, and add the statement to your registration page. If they are admitted, the legal items for children below are mandatory. |
| ☐ | **Which LLM providers** receive learner text, or `LOCAL_ONLY=true` | Hosted providers receive learner messages (see the review's data-flow table). |
| ☐ | **Whether voice features are offered**; raw audio is kept only with the learner's consent, for 30 days | Voice data may be biometric or sensitive data in some places. |
| ☐ | **Support and contact address** for privacy requests and security reports | Fill in the privacy notice and `SECURITY.md`. |
| ☐ | **How learners export or delete their data** | The API serves both (`GET /api/v1/privacy/export`, `DELETE /api/v1/privacy/data`) and the host CLI has `polyglot privacy`, but the web app has no buttons for them: handle requests by email with the CLI, or add the screens. |
| ☐ | **Incident contact** and escalation path | runbook, *Incident severity and escalation* |

## 3. Legal (needs qualified counsel; not done by the project)

Polyglot Swarm makes no compliance claim. These follow from the
[security and privacy review](security-privacy-review.md#obligations-to-assess-before-serving-real-learners-not-done-here).

| ✓ | Item | Notes |
|---|---|---|
| ☐ | Lawful basis for processing, and whether the learner model counts as profiling | GDPR / UK GDPR if any learner is in the EU or UK |
| ☐ | Privacy notice published and linked from the registration page | start from the [template](../legal/privacy-notice-template.md) |
| ☐ | Terms of use published | not provided by the project |
| ☐ | Data processing agreements with every hosted LLM provider you enable, with Microsoft (Edge TTS) if voice is on, and with your off-host backup storage provider | the backup copies are encrypted client-side, but a DPA may still be needed |
| ☐ | International transfer mechanism for providers outside the learners' jurisdiction | |
| ☐ | Children: COPPA (US), age-appropriate design codes (UK/EU), parental consent | only if minors are admitted |
| ☐ | Voice and biometric data rules | only if voice features are offered |
| ☐ | Retention statement matches the system: erased data persists in backups for up to 30 days | documented in the review and the runbook |

## Sign-off

| Role | Name | Date | Notes |
|---|---|---|---|
| Engineering | | | |
| Operator | | | |
| Legal counsel | | | |
