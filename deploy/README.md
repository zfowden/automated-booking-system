# Deploy: scheduled booking on Google Cloud

Architecture: **Cloud Scheduler** (cron, Europe/London) → **Cloud Run Job**
(Playwright container) → reads secrets from **Secret Manager** → books the slot
and pays by card → emails the result via **SendGrid**.

The job entrypoint is `tennis-book-job` (`src/tennis_booking/job.py`). It reads the
target booking frome `BOOK_*` nv vars and exits 0 on success / 1 on failure.

---

## ⚠️ Before you deploy: two things to verify

### 1. The paid checkout (Phase 0 — do this first, locally, headed)

The booking code fills a card form and pays, but the **exact checkout DOM has not
been verified**. Paid ClubSpark checkouts are often a third-party (Stripe/Opayo)
form inside an iframe, which automation frequently cannot fill. Verify before
trusting the schedule:

```bash
# Local, visible browser, dry-run (CONFIRM_PAYMENT=false => fills card, stops before paying)
CONFIRM_PAYMENT=false uv run tennis-book book --date <soon> --time <HH:MM>
```

Watch it reach the payment step. If it stops with a `PaymentError` dry-run message
after filling the card, the selectors work. If it can't find/fill the fields
(e.g. Stripe iframe), update the `SEL_CARD_*` / `SEL_PAY_*` selectors in
`src/tennis_booking/clubspark.py` against the live DOM (use
`uv run playwright codegen <checkout-url>`), or reconsider the payment approach.

### 2. Real money

`CONFIRM_PAYMENT=true` submits a real £12.50 payment. Keep it **false** until
you've confirmed the date/time/court logic end-to-end. Only set it true when you
genuinely want the job to spend money.

---

## One-time setup

```bash
export PROJECT_ID=your-project
export REGION=europe-west2               # London
export REPO=tennis                       # Artifact Registry repo
export JOB=tennis-book-job
export SA=tennis-booker

gcloud config set project "$PROJECT_ID"

# Enable APIs
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
    secretmanager.googleapis.com artifactregistry.googleapis.com

# Service account for the job + scheduler
gcloud iam service-accounts create "$SA" --display-name "Automated booker"
export SA_EMAIL="$SA@$PROJECT_ID.iam.gserviceaccount.com"

# Artifact Registry repo for the image
gcloud artifacts repositories create "$REPO" \
    --repository-format=docker --location="$REGION"
```

### Secrets

Create one secret per value. The job resolves these by name (see
`SECRET_ENV_NAMES` in `src/tennis_booking/secrets.py`).

```bash
for name in CLUBSPARK_USERNAME CLUBSPARK_PASSWORD SENDGRID_API_KEY \
            CARD_NUMBER CARD_EXPIRY CARD_CVV CARD_NAME CARD_POSTCODE; do
  gcloud secrets create "$name" --replication-policy=automatic 2>/dev/null || true
done

# Add values (repeat per secret; example shown for one):
printf '%s' 'your-lta-username' | gcloud secrets versions add CLUBSPARK_USERNAME --data-file=-
# ...add versions for the rest...

# Let the job's service account read them
for name in CLUBSPARK_USERNAME CLUBSPARK_PASSWORD SENDGRID_API_KEY \
            CARD_NUMBER CARD_EXPIRY CARD_CVV CARD_NAME CARD_POSTCODE; do
  gcloud secrets add-iam-policy-binding "$name" \
      --member="serviceAccount:$SA_EMAIL" --role=roles/secretmanager.secretAccessor
done
```

## Build & push the image

```bash
export IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$JOB:latest"
gcloud builds submit --tag "$IMAGE" .
```

## Create the Cloud Run Job

Secrets are injected by the client library at runtime (`USE_SECRET_MANAGER=true`),
so we only pass non-secret config + the booking target here.

```bash
gcloud run jobs deploy "$JOB" \
  --image "$IMAGE" --region "$REGION" \
  --service-account "$SA_EMAIL" \
  --memory 2Gi --cpu 2 --max-retries 1 --task-timeout 900s \
  --set-env-vars "USE_SECRET_MANAGER=true,GCP_PROJECT=$PROJECT_ID,EMAIL_PROVIDER=sendgrid,LOGIN_METHOD=lta,VENUE_SLUG=ClaphamCommon,EMAIL_FROM=you@example.com,EMAIL_TO=you@example.com,BOOK_DAYS_AHEAD=7,BOOK_TIME=18:00,BOOK_DURATION=60,BOOK_FALLBACKS=18:30,19:00,CONFIRM_PAYMENT=false"
```

Run it once manually and check logs / your inbox (dry-run first, `CONFIRM_PAYMENT=false`):

```bash
gcloud run jobs execute "$JOB" --region "$REGION"
gcloud run jobs executions list --job "$JOB" --region "$REGION"
```

When you're satisfied, redeploy with `CONFIRM_PAYMENT=true` to enable real bookings.

## Schedule it

Cloud Scheduler triggers the job via an OAuth-authenticated POST to the Run Admin
API. Courts open 7 days ahead at 00:00 UK, so this fires just after midnight London
time; the tool books `BOOK_DAYS_AHEAD` out.

```bash
gcloud scheduler jobs create http "$JOB-trigger" \
  --location "$REGION" \
  --schedule "1 0 * * *" \
  --time-zone "Europe/London" \
  --uri "https://run.googleapis.com/v2/projects/$PROJECT_ID/locations/$REGION/jobs/$JOB:run" \
  --http-method POST \
  --oauth-service-account-email "$SA_EMAIL"

# The scheduler SA also needs permission to run the job:
gcloud run jobs add-iam-policy-binding "$JOB" --region "$REGION" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/run.invoker
```

Adjust the cron (`minute hour day-of-month month day-of-week`) to the release
window; e.g. `1 0 * * 1` for Monday-only.

## Notes
- **Session**: the job logs in fresh every run (no persisted `storage_state.json`).
  The LTA login is a multi-hop Salesforce flow — expect the odd failure; you'll get
  a FAILED email with the error and an error screenshot in `/tmp/screenshots`.
- **Timezone**: the container sets `TZ=Europe/London`; the booking-window maths in
  `models.py` uses London time regardless of host clock.
- **Screenshots** on error go to `/tmp/screenshots` (ephemeral). To keep them,
  mount a GCS volume and point `SCREENSHOT_DIR` at it.
