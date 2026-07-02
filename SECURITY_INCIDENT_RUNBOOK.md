# EMERGENCY: credential rotation runbook

**Date discovered:** 2026-06-12
**Status: ACTIVE INCIDENT — do the steps in §1 today.**

## What happened

Commit `2e51e80` of this repo contains `electron/config.production.js` — a base64-encoded
JSON blob holding the **production Postgres credentials (Render) and AWS IAM access key +
secret key**. The repo is **public** at `github.com/MrHallooow/Sovalius_Hope_Review`, so these
credentials must be treated as fully compromised: credential-harvesting bots scan public GitHub
for AWS key patterns (base64 included) within minutes of a push. The file is also still tracked
by git (`.gitignore` does not untrack already-committed files), so every future commit keeps
carrying it.

Assume an attacker has: full read/write on the evidence Postgres database, and whatever the IAM
key allows on S3 (`sovalius-hope-evidence`) — likely read/write/delete of all evidence.

## 1. Today — rotate and contain (user actions, ~30 min)

1. **Make the repo private** (or delete it): GitHub → Settings → Danger Zone → Change
   visibility. Do this first; it stops *new* harvesting while you rotate. (It does not undo
   exposure — rotation is still mandatory.)
2. **Rotate the AWS IAM keys** (AWS console → IAM → Users → the HOPE user → Security
   credentials):
   - Create a new access key, update the device + review-app configs, then **deactivate and
     delete the old key**.
   - While there: check **CloudTrail** (event history, last 90 days) and **Billing** for
     activity you don't recognize — unusual S3 listing/downloads, new IAM users, EC2 launches
     (crypto-mining is the common abuse). Also check the S3 bucket for unexpected deletions.
3. **Rotate the Postgres password** (Render dashboard → the Postgres instance → Access
   Control / credentials). Render lets you regenerate the password; do it, then update:
   - `.env` on every reviewer machine
   - `env.production` / `electron/config.production.js` build inputs (see §2 — stop baking
     these into builds entirely)
   - the HOPE device's sync config (`SVG_HOPE_DATABASE_URL` env var on the rack)
4. **Audit the database for tampering** (after rotation): check `violations` and `audit_log`
   row counts/timestamps for anomalies around/after 2026-03-27 (the commit date of v1.6.2,
   when the file landed). The audit log was writable with the leaked credentials, so absence
   of audit entries is not proof of absence — compare against the device-side SQLite store
   (it is the primary; Postgres is the mirror).
5. **Change the seeded user passwords** in the production DB (`admin/admin123`,
   `sgt.williams/williams123`, `cpl.james/james123` are guessable and were in the public repo):
   use the app's change-password flow, or hash new ones with bcrypt and UPDATE the rows.

## 2. This week — stop the bleeding structurally

1. **Untrack the secret file** (keeps your local copy):
   `git rm --cached electron/config.production.js` then commit.
2. **Purge it from history** — rotation makes the old values worthless, but the file pattern
   invites the next mistake. Use `git filter-repo`:
   ```
   pip install git-filter-repo
   git filter-repo --invert-paths --path electron/config.production.js
   git push --force origin main
   ```
   (Coordinate with anyone who has clones; auto-updater release artifacts are unaffected.)
3. **Never bake credentials into the packaged app again.** The v1.6.1/v1.6.2 commits worked
   *around* asar packaging to keep credentials in the bundle — that means every distributed
   .exe contains the production credentials and anyone with the installer can extract them.
   This is the same trust-boundary problem as the audit's C-2 finding, and the durable fix is
   the API gateway (remediation plan Phase 1): the app authenticates officers against a
   service; no DB/S3 credentials exist on clients at all. Until then, at minimum keep
   credentials in the per-machine `.env` (never committed, never packaged).
4. **Enable GitHub secret scanning + push protection** on the repo (Settings → Code security)
   once it's private — it blocks pushes containing key patterns.

## 3. Done already (this session, by Claude)

- `setup-users.js` now refuses to run outside `NODE_ENV=development` (or `--dev`) and
  generates random one-time passwords instead of hardcoded ones.
- Verified `.env` and `env.production` themselves were never committed; the exposure is the
  `config.production.js` blob in `2e51e80` (current HEAD) only.
- SVG_HOPE daemon side: stream reads now require a token, the anonymous-auth env override is
  debug-only, and login is rate-limited with lockout (see SVG_HOPE repo changes).

## 4. Open items (tracked in the remediation plan)

- C-2 API gateway (Phase 1) — removes client-side credentials permanently.
- C-5 closeout — per-component IAM principals (device: putObject-only; review: getObject-only),
  scheduled rotation, secret-scanning CI hook in both repos.
