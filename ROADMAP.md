# SenteCheck — Product Roadmap

> Betting finance tracker for Ugandan bettors. Tracks MTN and Airtel mobile money
> transactions via SMS, classifies betting deposits and withdrawals automatically,
> and surfaces P&L reports through a Telegram bot.

---

## Current State (March 2026)

### What works today
- Android app intercepts MTN/Airtel mobile money SMS and forwards them to the backend
- Backend parses all major Uganda SMS formats (MTN out/in/withdrawal, Airtel out/in/withdrawal)
- Unknown merchants trigger a Telegram classification prompt (Yes/No inline keyboard)
- Once classified, merchants are remembered permanently — the same merchant is never asked about again
- Full Telegram bot command set:
  - `/summary` — total deposited vs withdrawn, net P&L, win rate
  - `/losses` / `/wins` — dashboards with recent history
  - `/history [n]` — last n transactions
  - `/bankroll set/status` — monthly budget tracking with health indicator and recommended stake
  - `/bet` — manual bet logging with win/loss/pending result
  - `/merchants` — list all known merchant classifications
  - `/addmerchant` — manually classify a merchant
  - `/mydata` — full data export summary
  - `/deleteaccount` — GDPR-compliant permanent deletion

### What needs to happen next
- Auth: single shared webhook secret does not scale beyond one user
- No freemium tier enforcement
- No payment collection mechanism
- No public distribution

---

## Phase 1 — Multi-user Ready

**Goal:** Let other people use SenteCheck without sharing your webhook secret.

### 1.1 Per-user API keys
- On `/start` + consent, generate a unique 32-character API key per user
- Store it hashed in the database (same as a password — never store plaintext)
- Display it once in the onboarding message: `Your API key: XXXX-XXXX-XXXX`
- Android app replaces the "Webhook Secret" field with "API Key"
- Backend validates the key against the user's stored hash, not a global env var
- Old shared `WEBHOOK_SECRET` becomes an admin-only fallback

### 1.2 Freemium tier
Free users:
- 3 betting merchant slots (betting sites they can classify and track)
- Unlimited other merchants (salaries, bills, etc. — not betting)
- Full access to all commands
- Summary shows lifetime data

Paid users (UGX 5,000/month or similar):
- Unlimited betting merchants
- Priority classification (future: faster response)
- Monthly PDF/CSV export (future)

**Implementation:**
- Add `plan` column to User: `free` or `premium`
- Add `premium_until` date column
- When a free user tries to classify a 4th betting merchant, block it and send:
  > "You've reached the 3 betting site limit on the free plan. Upgrade for unlimited tracking — /upgrade"
- `/upgrade` shows payment instructions

### 1.3 Payment collection
- Accept MTN MoMo and Airtel Money payments to a registered business number
- User sends payment, forwards the confirmation SMS to the bot: `/upgrade [SMS text]`
- Bot parses the SMS (using the existing parser), verifies amount and sender, sets `premium_until` to +30 days
- No payment gateway needed — the SMS parser we already built handles verification

---

## Phase 2 — Polish

**Goal:** Smooth enough for strangers to use without hand-holding.

### 2.1 Onboarding improvements
- After `/start` and consent, send a second message with a setup checklist:
  > ✅ Account created
  > ⬜ Android app installed — [Download here](link)
  > ⬜ API key entered in app
  > ⬜ First SMS forwarded
- `/status` command shows connection health (last SMS received time)

### 2.2 Smarter classification prompts
- Currently asks: "Was this a bet deposit?" — binary yes/no
- Upgrade to: show merchant name + amount more prominently, add a "Remind me later" option
- If user ignores a prompt for 24 hours, auto-classify as "other" to keep data clean

### 2.3 Weekly digest
- Every Monday, bot sends a weekly P&L summary automatically (opt-in via `/digest on`)
- Shows the week's deposits, withdrawals, net position, and a brief comparison to the week before

### 2.4 /summary time filters
- `/summary` — all time (current)
- `/summary week` — this week
- `/summary month` — this month
- `/summary [month name]` — e.g. `/summary march`

---

## Phase 3 — Distribution

**Goal:** Get the APK into people's hands without the Play Store.

### 3.1 Landing page
- Single-page site: what SenteCheck does, screenshots, download button for the APK
- Host on GitHub Pages (free) or Netlify
- Domain: sentecheck.app or similar (~$10/year)
- The APK download link points to the GitHub releases page

### 3.2 Samsung Galaxy Store
- Less strict than Google Play for SMS permission apps
- Pre-installed on every Samsung phone (dominant in Uganda)
- Requires: app icon (done), screenshots, privacy policy, store description
- Submit at seller.samsungapps.com — free to register

### 3.3 APKPure / Aptoide
- Upload the signed APK directly
- Reaches Android users who already use alternative stores
- No review process, live within hours

### 3.4 WhatsApp/community distribution
- Share the APK download link directly in Ugandan betting/finance WhatsApp groups
- The Telegram bot is the product — the APK is just the SMS bridge
- Word of mouth works well for tools that save people money

---

## Phase 4 — Infrastructure Independence

**Goal:** Not dependent on Railway continuing to work or remaining affordable.

### Hosting options (ranked by value)

| Option | Cost | Effort to migrate | Notes |
|--------|------|-------------------|-------|
| Oracle Cloud free tier | Free | Medium | Always-free ARM VM, enough for this app |
| Fly.io | ~$3/month | Low | Docker-based, easy migration from Railway |
| Hetzner VPS | ~$4/month | Low | Very reliable, EU-based |
| Render | Free (cold starts) | Low | Similar to Railway |
| DigitalOcean | $6/month | Low | Good Uganda latency via their Singapore region |

**Migration is already easy** because the entire app runs in Docker. Moving means:
1. Provision a new server
2. Set the same environment variables
3. Point Railway's domain DNS to the new server (or update Telegram webhook URL)
4. Done

### Database
- Railway PostgreSQL is fine for now
- When moving: export with `pg_dump`, import on the new host
- Consider Supabase (free PostgreSQL tier, 500MB) as a managed alternative

### Telegram webhook
- Only one URL is registered at a time
- Changing hosting = one API call to update the webhook URL
- No downtime needed for the Android app (it talks to the backend, not Telegram)

---

## Monetization Strategy

### Pricing (Uganda market)
- **Free:** 3 betting merchants tracked, all features
- **Premium:** UGX 5,000/month (~$1.35) — unlimited merchants, future extras

### Why this model works
- Free tier is genuinely useful — most people only bet on 1-2 sites
- 3-site limit is hit naturally as users get value and want more
- UGX 5,000 is less than one typical bet — easy to justify
- Payment via mobile money removes the need for cards (most Ugandans don't have one)

### Revenue path
- 100 free users trying the app
- 20% convert to paid = 20 users × UGX 5,000 = UGX 100,000/month (~$27)
- Break-even covers hosting costs immediately
- At 500 paid users: UGX 2.5M/month — meaningful income

### Future monetization (when user base is larger)
- Betting site partnerships (referral fees for users who sign up via SenteCheck)
- Anonymised aggregate data insights (total betting spend by region, by site)
- Premium features: CSV export, multi-month comparisons, bet slip OCR

---

## SMS Formats — Current Coverage

| Network | Type | Status |
|---------|------|--------|
| MTN | Send to person | ✅ |
| MTN | Business deduction | ✅ |
| MTN | Cash withdrawal at agent | ✅ |
| MTN | Receive from business | ✅ |
| MTN | Receive cross-network (from Airtel) | ✅ |
| Airtel | Cash deposit | ✅ |
| Airtel | Send to person or business | ✅ |
| Airtel | Cash withdrawal at agent | ✅ |
| MTN | Receive same-network person | ⬜ (no sample yet) |
| Airtel | Business deduction | ⬜ (likely same as send format) |
| Airtel | Virtual card load | ⬜ (skipped — wallet accounting edge case) |

New formats are added as they appear in production — paste the SMS and it's a 10-minute fix.

---

## Build Order for Next Phase

1. Per-user API keys (Phase 1.1) — blocks everything else
2. Android app: replace webhook secret field with API key field
3. Freemium enforcement (Phase 1.2)
4. `/upgrade` command + MoMo payment verification (Phase 1.3)
5. Landing page + APK release on GitHub (Phase 3.1)
6. Samsung Galaxy Store submission (Phase 3.2)
7. `/summary week/month` filters (Phase 2.4)
8. Weekly digest opt-in (Phase 2.3)
9. Set up Oracle Cloud or Fly.io as Railway backup (Phase 4)
