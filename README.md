# PennyWatch

A project of **Antipodean Affairs** — an open, auditable tracker of public statements (both **critical** and **positive**) issued by Senator Penny Wong, Australian Minister for Foreign Affairs, on her X account [@SenatorWong](https://x.com/SenatorWong), since her swearing-in on 1 June 2022.

Every entry is sourced to a specific tweet, attributed to the country, government, or official it concerns, and tagged on one of two scales: a four-tier critical scale (Condemn, Criticise, Concern, Call for action) or a four-tier positive scale (Endorse, Commend, Appreciate, Solidarity). A single tweet may register on both at once (e.g. praising a people while criticising their government). The classifier rules and full target list are published on the site itself so readers can audit, dispute, or replicate the counts.

The output is a single static HTML file you can host anywhere (GitHub Pages, Netlify, Cloudflare Pages, a USB stick).

## What's in this folder

| File | Purpose |
|---|---|
| `index.html` | The rendered tracker site — open in a browser. |
| `index.template.html` | HTML template; the pipeline injects the data into it. |
| `build_tracker.py` | Fetcher, classifier, and site-renderer (one script, stdlib only). |
| `seed_tweets.json` | Hand-crafted sample tweets so the site renders before you plug in an API key. **Clearly labelled "[SAMPLE DATA]" — not real Wong tweets.** |
| `tweets.json` | Full classified dataset (regenerated each run). |
| `summary.json` | Precomputed counts by country, severity, and month. |
| `METHODOLOGY.md` | The rules: trigger words, target list, severity tiers, exclusions, limitations. **Read this before defending the numbers.** |

## Quickstart (see the site with sample data)

```bash
python3 build_tracker.py --seed
open index.html         # macOS — or just double-click it
```

## Real data — plug in an X API key

1. Sign up at [developer.x.com](https://developer.x.com) and create an app. The **Basic** tier (~USD 200/month at time of writing) is required for `/2/users/:id/tweets` access.
2. Generate a Bearer Token from the app's Keys and Tokens page.
3. Run the pipeline:

   ```bash
   export X_BEARER_TOKEN="YOUR_TOKEN_HERE"
   python3 build_tracker.py
   ```

   This will fetch all tweets since 1 June 2022, classify them, and regenerate `index.html`. Expect a few thousand tweets and several minutes of paginated requests; the script handles 429 rate-limit responses by sleeping until the reset.

4. If you want to refine the classifier without re-fetching from X:

   ```bash
   python3 build_tracker.py --no-fetch
   ```

## Tuning the classifier

Edit two lists at the top of `build_tracker.py`:

- `TRIGGERS` — the keyword patterns that determine inclusion and severity tier
- `TARGETS` — country and official name patterns
- `NON_STATE` — non-state actors (recorded separately, don't contribute to country counts)
- `EXCLUSION_PATTERNS` — phrases that flag a tweet as "needs review"

When you change any of these, bump `METHODOLOGY_VERSION` in `build_tracker.py` **and** the version number in `METHODOLOGY.md`, and add a changelog entry. The site shows the version so readers can tell what ruleset produced the displayed counts.

## Hosting

Any static host works. Two recommended paths:

### Netlify Drop (fastest, anonymous)

Drag this folder onto [app.netlify.com/drop](https://app.netlify.com/drop). Site is live in under a minute. No account, random subdomain (you can claim it later).

### GitHub Pages (recommended for a public, auditable project)

1. Create a GitHub repository (e.g. `pennywatch`).
2. Push this folder to it. **Before your first commit**, set the git author identity to your pen name:

   ```bash
   cd pennywatch-source
   git init
   git config user.name "Antipodean Affairs"
   git config user.email "your-pen-name-email@proton.me"
   git add .
   git commit -m "Initial publication"
   git branch -M main
   git remote add origin https://github.com/<your-username>/pennywatch.git
   git push -u origin main
   ```

3. In the repo's **Settings → Pages**, set source to "Deploy from a branch", branch `main`, folder `/ (root)`. Pages will serve `index.html` at `https://<your-username>.github.io/pennywatch/`.

4. To refresh: run `python3 build_tracker.py` locally, then `git commit -am "Refresh data" && git push`. Or set up a scheduled GitHub Action with `X_BEARER_TOKEN` as a repo secret.

### Publishing under a pseudonym — discipline notes

If Antipodean Affairs is meant to be unattributable:

- The pen name and the email it signs up for hosting with become permanently linked. Use a fresh email (Proton/Tuta) not associated with your real-name browsing or recovery contacts.
- Git commit metadata bakes the author name and email into the commit forever. Set `git config user.name` / `user.email` to the pen name **before** the first commit. A leak here is essentially un-fixable on a public repo.
- Skip custom domains for v1 — `username.github.io/pennywatch` reveals nothing. If you do want a domain, use a registrar that turns on WHOIS privacy by default.
- Use a separate browser profile for the pseudonymous accounts. Never log in from a device that also has your real-name accounts open in the same session.
- Defamation in Australia attaches to the publisher; pseudonyms can be pierced by court order. A neutral tally with linked sources is safer than interpretive commentary.

## On credibility

A tracker like this only helps the public conversation if it can withstand scrutiny. A few things worth thinking about before you publish:

- **Show your work.** Link `METHODOLOGY.md` from the site (already done) and link the tracker's source repo. People who disagree with your numbers should be able to point at the exact rule they disagree with.
- **The counts alone don't prove bias.** A higher count for country X may reflect that X did more newsworthy things in the period, not that the foreign minister is biased. A fair presentation acknowledges this. The limitations section in `METHODOLOGY.md` says so explicitly — keep it.
- **Comparable baselines help.** If you want the chart to mean something, the natural comparison is to the same metric applied to comparable democracies' foreign ministers — e.g. the UK Foreign Secretary, the Canadian Minister of Foreign Affairs, the NZ Minister of Foreign Affairs over the same period. The pipeline is small enough that adding a second handle is trivial; happy to extend it if you want.
- **The X feed is not the complete record.** Press releases, joint statements, Senate speeches, and doorstop interviews aren't in here. Note this prominently if you publish.
