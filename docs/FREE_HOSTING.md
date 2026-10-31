# Temporary free hosting research

Verified against official sources on **2026-10-31**. Research only: no account,
card, deployment, publication, or hosting choice has been authorized or assumed.

## Suggested first option: Render Free + Neon Free

Pending acceptance of the cold-start limitation, this is the smallest adaptation
for the existing Python ASGI/MCP application. These are recurring free tiers,
not introductory credit balances.

Render provides a public `*.onrender.com` address and managed TLS. Its free web
service receives 750 instance-hours per workspace per month. After 15 minutes
without incoming traffic it sleeps; waking takes about one minute. **That
conflicts with the target Claude discovery/token timeout of 10 seconds.** Opening
the website first and waiting for readiness is only a temporary testing
workaround, not a guarantee of seamless MCP connection or OAuth completion.
Restarts can happen independently of inactivity.

**Keeping SQLite on Render's local filesystem is unsafe:** files disappear on
sleep, restart, and redeploy; persistent disks are unavailable on free services.
Render's own free Postgres expires after 30 days, so it is not the proposed DB.
Outbound API/database access is supported, but unusually high service-initiated
traffic can cause suspension. Steam HTTPS access is a reasonable architectural
fit, not a verified successful request from a deployed instance.

Without a payment method, exceeding bandwidth suspends free services instead of
billing; build-quota exhaustion disables new builds. Official docs describe
operation without a payment method, but do not establish that every account is
exempt from individual verification. Do not attach a card or enable paid
services without approval; a card can change overage billing behavior.

Sources: [Render Free](https://render.com/docs/free),
[first deployment](https://render.com/docs/your-first-deploy),
[service types](https://render.com/docs/service-types).

### Neon database

Neon's current Free plan explicitly states **$0, no time limit, no credit card**:
100 CU-hours/month/project, 1 GB Postgres storage/project (20 GB account total),
and 5 GB public network transfer/project. Compute sleeps after five minutes;
ordinary stored tables remain durable. Typical reactivation takes hundreds of
milliseconds, but this is not a latency guarantee. Exhausting compute/transfer
pauses compute until the next billing period or an explicit upgrade. Storage
limits reject storage-increasing operations; these limits do not delete data.

Sources: [pricing](https://neon.com/pricing),
[plans and quota behavior](https://neon.com/docs/introduction/plans),
[compute lifecycle](https://neon.com/docs/introduction/compute-lifecycle).

### Required application changes before deployment

- Replace SQLite access with a PostgreSQL adapter and TLS `DATABASE_URL`.
- Persist OAuth clients/grants, authorization codes, refresh-token records,
  device approval state, Steam bindings, and pending OpenID state/nonces in
  ordinary durable tables; do not rely on process memory or temporary tables.
- Preserve expiration checks, atomic one-time code consumption, and transactional
  refresh/approval operations. Restart survival must not resurrect used codes.
- Keep signing/session secrets stable in environment configuration; configure a
  fixed HTTPS issuer/base URL and exact callback URLs. Bind ASGI to
  `0.0.0.0:$PORT`, initially with one worker.
- Verify restart survival during pending login/device approval, refresh behavior,
  Steam connectivity, and cold discovery/token requests before calling it ready.

## Fallback: Cloudflare Workers Free + D1

Worth considering if Render's sleeping VM is unacceptable. It is **not a
drop-in hosting move** for the present Python ASGI process. A practical supported
route ports the HTTP/MCP/auth layer to the TypeScript Workers/Agents SDK and
durable state to D1. Python Workers exist; compatibility of the current Python
MCP dependencies has not been established.

Workers Free includes 100,000 requests/day and **10 ms CPU per invocation**;
D1 includes 5 million rows read/day, 100,000 written/day and 5 GB total storage.
Measure auth/serialization CPU before choosing it. The official remote MCP guide
supports Streamable HTTP at `workers.dev/mcp` and explicitly requires persistent
state in storage bindings. No free-tier latency SLA is established. The reviewed
official sources did not independently establish a universal no-card signup
promise; do not enable a paid subscription or assume unlimited operation.

Sources: [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/),
[D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/),
[remote MCP guide](https://developers.cloudflare.com/agents/model-context-protocol/guides/remote-mcp-server/).

## Not preferred: Koyeb Free

One 512 MB/0.1 vCPU instance, sleeps after one hour, no persistent volume. Signup
requires a card with a **$29 authorization hold**, potentially unreleased for
7–21 days. Spending caps are not available according to its FAQ. This is a poor
match for a no-financial-commitment experiment, despite free compute.

Sources: [instances](https://www.koyeb.com/docs/reference/instances),
[pricing FAQ](https://www.koyeb.com/docs/faqs/pricing).
