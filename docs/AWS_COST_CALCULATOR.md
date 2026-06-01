# AWS Cost Calculator — Starting Scale (≤ 10 users/week)

Estimated monthly AWS cost for the **beginning phase**: at most **10 users per
week**. Prices are **rough `us-east-1` estimates** — confirm in the AWS Pricing
Calculator. Goal: pick the **cheapest practical** setup and list the knobs to
keep it cheap.

> **Separate from AWS:** the **RapidAPI provider subscriptions** (Kiwi, Kayak,
> Skyscanner) are billed by RapidAPI, *not* AWS. At low volume their free/basic
> tiers may cover you, but this is likely your **largest real cost** — see §6.

---

## 1. Traffic assumptions

| Metric | Assumption | Derivation |
|--------|-----------|------------|
| Users | ≤ 10 / week | ≈ 40 / month |
| Searches | ~5 per user | ≈ **200 searches / month** |
| Provider calls | 2 (fast) + 3 (full) per search | ≈ 1,000 RapidAPI calls / month |
| Watcher | every 30 min, a few watches | ≈ 1,440 ticks / month |
| Emails (alerts) | a few price drops | < 50 / month |
| Data stored | users + watches JSON | **kilobytes** |
| Egress | small JSON + static assets | a few GB / month |

This is **tiny** — most managed services sit inside their always-free tiers.

---

## 2. Scenario A — Lightsail monolith (recommended to start) 💰

One small instance runs the app **and** serves the static frontend, exactly as
today. No refactor. Free TLS via Caddy/Let's Encrypt.

| Item | Spec | Est. $/mo |
|------|------|-----------|
| Lightsail instance | 1–2 GB Graviton (arm64) | **$5 – $10** |
| TLS certificate | Caddy + Let's Encrypt (free, auto-renew) | $0 |
| Route 53 hosted zone | 1 zone | $0.50 |
| Domain registration | `.com` (~$13/yr) | ~$1.10 |
| SES email | < 50 emails × $0.10/1k | < $0.01 |
| Instance snapshots | daily, few GB | ~$0.50 |
| **Total** | | **≈ $7 – $12 / mo** |

✅ Cheapest practical. No code change. No load balancer. Handles the 40 s
Skyscanner call fine (persistent runtime, no gateway timeout).

---

## 3. Scenario B — Static split + Fargate API (cloud-native, 3-tier)

Static frontend on **S3 + CloudFront**; **Fargate** runs only `/api/*`;
**DynamoDB** for state. More moving parts, still cheap at this volume.

| Item | Spec | Est. $/mo |
|------|------|-----------|
| Fargate task (always on) | 0.25 vCPU / 0.5 GB | **~$9** |
| S3 (static hosting) | few MB + tiny requests | < $0.10 (free tier) |
| CloudFront | < 1 TB out (free tier 1 TB + 10M req) | **$0** |
| DynamoDB | on-demand, KB of data | **$0** (free tier) |
| ACM certificate | public cert w/ CloudFront | **$0** |
| Route 53 zone + domain | | ~$1.60 |
| SES email | < 50 | < $0.01 |
| CloudWatch logs | short retention | < $0.50 |
| **Total** | | **≈ $11 – $13 / mo** |

⚠️ **Avoid:** a NAT Gateway (~$32/mo) — put the task in a **public subnet with a
public IP**, no NAT. And **no ALB** (~$16/mo) — front the API via CloudFront
origin or a separate `api.` subdomain.

---

## 4. Scenario C — Full serverless (cheapest at idle) 🪙

Lambda (via Mangum) + HTTP API + DynamoDB + EventBridge for the watcher.

| Item | Spec | Est. $/mo |
|------|------|-----------|
| Lambda | ~200 req + 1,440 watcher invocations | **$0** (free tier 1M req) |
| API Gateway (HTTP API) | ~200 req | **~$0** ($1/million) |
| DynamoDB | on-demand | **$0** (free tier) |
| S3 + CloudFront | static | **$0** (free tier) |
| EventBridge Scheduler | 1,440 invocations | **~$0** |
| Route 53 + domain | | ~$1.60 |
| SES | < 50 | < $0.01 |
| **Total** | | **≈ $2 / mo** |

⚠️ **Caveat:** API Gateway has a **hard 29 s timeout**; the full-tier Skyscanner
call (~40 s cold) **will fail**. Requires a refactor: return the fast tier
synchronously, deliver the full tier via async polling/WebSocket. Cheapest, but
the most work.

---

## 5. Comparison

| Scenario | Effort | Est. $/mo | Best when |
|----------|--------|-----------|-----------|
| **A. Lightsail monolith** | None (lift-and-shift) | **$7 – $12** | **Start here** — cheapest practical |
| B. S3/CloudFront + Fargate | Medium | $11 – $13 | Want managed/3-tier, no server to patch |
| C. Full serverless | High (async refactor) | **~$2** | Bursty/rare traffic + willing to refactor |

**Recommendation for ≤ 10 users/week: Scenario A.** At this volume the fancy
architectures don't save money — a single $5–10 instance wins on cost *and*
simplicity. Revisit B/C only when traffic grows or you need managed scaling.

---

## 6. The real cost driver: RapidAPI

~1,000 provider calls/month. Check each API's plan on RapidAPI:
- Free tiers exist but often cap calls/month and rate-limit hard.
- Paid basic tiers commonly **$10 – $50/mo each**.
- This can **exceed the entire AWS bill**. Optimize by: caching results per
  route+date, lowering watcher frequency (30 → 60 min), and only calling the
  slow Skyscanner tier on demand (already the two-phase design).

---

## 7. Domain & certificate (your question)

- **Public endpoint:** yes — users need a reachable URL. The app's **static
  frontend *is* the public site**; you do **not** need a separate marketing site.
- **Domain:** optional. You can run on the raw CloudFront / Lightsail URL. A
  custom domain (~$13/yr via Route 53, +$0.50/mo hosted zone) is nicer and
  needed for a branded HTTPS cert.
- **Certificate approval = domain validation:**
  - **CloudFront / ALB / API Gateway → ACM public cert, free**, DNS-validated.
    If the domain is in Route 53, validation is essentially one-click and the
    cert **auto-renews**.
  - **Lightsail / EC2 (direct) →** ACM can't attach without an AWS load
    balancer, so use **Caddy / Let's Encrypt** (free, auto-renew). The "approval"
    is an automatic HTTP/DNS challenge.
- Net: **no cost for the certificate** in either path; only the domain (~$13/yr)
  is a real charge, and even that is optional to begin with.

---

## 8. Cost-optimization checklist

- ✅ **One small Graviton (arm64)** instance — cheaper than x86.
- ✅ **No ALB** (~$16/mo) and **no NAT Gateway** (~$32/mo) at this scale.
- ✅ **Free TLS** — ACM (managed endpoints) or Caddy/Let's Encrypt (instance).
- ✅ Lean on **always-free tiers**: CloudFront 1 TB, DynamoDB 25 GB, S3, Lambda.
- ✅ **Cache provider results** + lower watcher frequency → cuts RapidAPI cost.
- ✅ **CloudWatch log retention** 7–14 days (don't keep logs forever).
- ✅ **AWS Budgets alarm** at e.g. **$15/mo** to catch surprises early.
- ✅ Consider a **1-yr Savings Plan / Lightsail** (already low) once stable.
- ✅ Start on **Scenario A**; only graduate to B/C when traffic justifies it.

**Bottom line:** at ≤ 10 users/week, expect **≈ $7–12/mo of AWS** (Lightsail) —
and watch the **RapidAPI subscriptions**, which are likely the bigger bill.
