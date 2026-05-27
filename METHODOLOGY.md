# PennyWatch — Methodology

*Published by Antipodean Affairs.*

PennyWatch counts public statements by Senator the Hon. Penny Wong, Australian Minister for Foreign Affairs, directed **critically or positively** at named foreign countries, governments, or named foreign ministers/officials. Statements are sourced from her official X account, [@SenatorWong](https://x.com/SenatorWong), back to her swearing-in on **1 June 2022**.

Trackers of this kind are only as credible as their inclusion rules. We publish ours in full so readers can audit, dispute, or replicate them.

## What counts as a tracked statement

A tweet (or thread) is included if **both** of the following are true:

1. **It contains a critical OR positive trigger** — a word or phrase from one of the lists below.
2. **It identifies a target** — a country, government, regime, or named foreign minister/official from the target list below.

Retweets and quote-tweets are included only when Senator Wong adds her own commentary. Pure retweets without added commentary are excluded. A single tweet may be both critical and positive (e.g. praising a country's people while criticising its government); these are recorded as **mixed** and appear in both views.

## Critical severity tiers

Each critical statement is tagged with one of four tiers. This lets readers filter and avoids collapsing a polite "we are concerned" into the same bucket as an outright "we condemn".

| Tier | Trigger words (non-exhaustive) | Example phrasing |
|---|---|---|
| **Condemn** | condemn, condemnation, denounce, denounces | "Australia condemns…" |
| **Criticise** | deplore, unacceptable, abhorrent, outrageous, reject, appalled, atrocity, sanctions | "These actions are unacceptable" |
| **Concern** | concerned, deeply concerned, troubled, alarmed, dismayed, disturbed, regret | "Australia is deeply concerned by…" |
| **Call for action** | must end, must stop, must cease, must release, demand, call on [X] to, urge [X] to | "We call on the regime to release…" |

A single statement is assigned the **strongest** tier it qualifies for.

## Positive warmth tiers

The mirror image. Added in v1.2 because a critical-only tally tells half a story — a foreign minister's public record is the sum of what they choose to celebrate as well as what they choose to condemn.

| Tier | Trigger words (non-exhaustive) | Example phrasing |
|---|---|---|
| **Endorse** | congratulate, commend, applaud, salute, warmly welcome, celebrate, honour | "Australia warmly congratulates…" |
| **Commend** | welcome, proud, pleased to welcome/meet/host, strongly support, delighted | "Pleased to host PM X in Canberra" |
| **Appreciate** | thank, grateful, appreciate, value, recognise, close partner / partnership / friendship, enduring partnership | "We are grateful for our close partnership with…" |
| **Solidarity** | thoughts with, hearts go out, condolences, mourn, stand with the people of, in solidarity with | "Our thoughts are with the people of X" |

The **Solidarity** tier captures expressions of sympathy and standing-with that v1.0 excluded entirely. We now count these as positive-toward statements, because choosing to make them is itself a foreign-policy signal — just as choosing not to make them is.

## Target list

A statement only counts if the target is identifiable. We track three target categories.

**Country / government** — e.g. "Russia", "Iran", "the Myanmar military regime", "the Israeli cabinet", "Japan", "Indonesia".

**Named foreign official** — any named head of state, head of government, cabinet minister, senior military commander, or other senior government official. **Criticism (or praise) of a named official is attributed to their country.**

- *Critical example:* a statement criticising Israeli National Security Minister **Itamar Ben-Gvir** is recorded as a statement targeting **Israel**.
- *Critical example:* a statement criticising Russian Foreign Minister **Sergei Lavrov** is recorded as a statement targeting **Russia**.
- *Positive example:* a statement praising Indonesian President **Prabowo** or thanking PNG PM **James Marape** is recorded as a positive statement toward **Indonesia** / **Papua New Guinea**.

This rule covers serving officials and (for the duration of their tenure) recent former officials whose conduct in office is being criticised or praised.

**State entity** — e.g. "the IRGC", "the Russian Foreign Ministry", "the IDF General Staff", "the Indonesian Coast Guard".

Named individuals affiliated with a **non-state actor** (e.g. Yahya Sinwar / Hamas, Hassan Nasrallah / Hezbollah) attribute to the non-state actor — they do **not** contribute to any country's total.

References to a region without a clear state target ("we are concerned about the situation in the Middle East") are **excluded**. If one statement targets multiple actors (e.g. "Russia and Iran"), it is counted **once per distinct target**.

## Sentence-level tone scoping

When a tweet contains both critical and positive language, targets are attributed based on the **sentence** in which they appear. A target receives a critical tier only if it appears in a sentence containing a critical trigger; it receives a positive tier only if it appears in a sentence with a positive trigger.

*Example:* "Australia condemns Russia's invasion of Ukraine. We stand with the Ukrainian people."

- **Russia** is recorded as a Condemn target (it appears in the first sentence with "condemns").
- **Ukraine** is recorded as a Solidarity target (it appears in the second sentence with "stand with").
- Russia is **not** credited with the Solidarity statement, despite both words appearing in the same tweet.

This rule prevents the most common false-positive pattern in mixed tweets and is core to the integrity of the positive-statements view.

## Edge cases

- **Joint statements.** Tweets attributed to a joint statement (AUKUS, Quad, G7) are included only if Senator Wong personally posts them from her account.
- **Domestic political commentary.** Excluded — this tracker is about foreign-policy statements only.
- **Statements about Australian citizens detained abroad.** Included as **critical** if they criticise the detaining state ("we call on [country] to release…"); excluded if purely consular/welfare in nature.
- **Sanctions announcements.** Included — recorded as a **Criticise**-tier critical statement at minimum.
- **Hamas, Houthis, and other non-state actors.** Recorded but tagged as non-state. They do not contribute to any country's total unless the tweet separately names a country.
- **A tweet praising a people while criticising their government** (e.g. "We stand with the brave women of Iran against the regime") is recorded as **mixed** — both Solidarity-positive and the strongest critical tier the regime criticism triggers, both attributed to Iran.

## Known limitations

This list is published deliberately, because every tracker of this kind has these limitations and most don't say so.

1. **Keyword-based classification has false positives and false negatives.** A tweet that says "Australia condemns the attacks by X on Y" tags both X and Y as targets, even though the criticism is only of X. Praise of an *individual* who happens to share a name with a country term will mis-attribute. We flag low-confidence cases for manual review, but reviewers should always read the underlying tweet before drawing inferences from a single row.
2. **The X feed is not the complete record.** Ministerial press releases, joint statements at multilateral fora, Senate speeches, and doorstop interviews are not captured. A minister who criticises a country in a press release but not on X will be under-counted here.
3. **The denominator matters.** A raw count of "country X was criticised N times" is not, on its own, evidence of bias. It must be read alongside (a) the volume of newsworthy events involving each country in the period, (b) the criticism levelled at each country by comparable democracies' foreign ministers, and (c) the positive-statement count for the same country — which is exactly what the positive view on this page is for.
4. **Translation and transliteration.** Country and minister names with multiple spellings (e.g. "Myanmar" vs "Burma", "Erdoğan" vs "Erdogan", "Ben-Gvir" vs "Ben Gvir") are normalised in the target list.

## Updating the methodology

When the trigger word list or target list changes, the version number is bumped and a changelog entry is added. The site shows the methodology version used to compute the displayed counts.

### Changelog

- **v1.4.2** (2026-05-27) — **Location-context exclusion.** Bundled with v1.4.1's perpetrator-pattern exclusion. When a country appears in a clause like "Australians depart [country] & the Occupied Palestinian Territories" or "evacuate from [country]" or "stranded in [country]", that country is being referenced as the *location* of trouble Australians are leaving — not as a recipient of any positive sentiment the sentence may express toward a separate helper country. The detected patterns are: `depart`, `leaving`, `evacuate`, `flee`, `escape`, `exit`, `stranded in`, `trapped in`, `stuck in`, `caught in`, each followed by up to 80 chars of context. Countries detected here are excluded from `positive_targets` for that sentence; they remain eligible for `critical_targets` if a separate critical signal applies. Surfaced by tweets like "thanking @AymanHsafadi for Jordan's work assisting Australians depart Israel & the Occupied Palestinian Territories" and "Thank you to the UAE leadership for their support of our work to assist Australians leaving Israel" — both were wrongly attributing Appreciate sentiment to Israel and Palestine instead of only to the helper countries.
- **v1.4.1** (2026-05-27) — **Perpetrator-pattern exclusion.** Mirror of the v1.3.2 victim-pattern exclusion. A tweet like "Australia stands with Ukraine against Russia's brutal invasion" was previously crediting Russia with Solidarity (positive) because both countries appeared in a sentence containing "stand with". v1.4.1 detects oppositional framing — `[country]'s [aggression-noun]` (e.g., "Russia's invasion"), `[country]'s [critical-adjective] regime/government/...` (e.g., "Putin's oppressive regime"), `against [country]`, and `hold [country] accountable` — and treats the named country as the *perpetrator* of the action being criticised, not a recipient of any positive sentiment. Perpetrator countries are: (a) excluded from `positive_targets` for the sentence, and (b) tagged with Condemn severity in `critical_targets` regardless of what other triggers fired. Importantly, the attribution logic now distinguishes severity that came from an *explicit critical trigger* (which propagates to all non-excluded targets in the sentence) from severity forced by *perpetrator-context* (which propagates only to the perpetrator countries). This prevents non-perpetrator targets like Ukraine from being mis-tagged as critical in sentences whose only critical signal is a perpetrator-context mention of another country. Content-neutral: the patterns apply symmetrically across all countries.
- **v1.4.0** (2026-05-27) — **Incremental fetching.** Earlier versions did a full backfill from 1 June 2022 on every scheduled run, burning roughly 2,000 X API reads each time and nearly exhausting the Basic-tier 10,000/month quota in a single day of testing. v1.4.0 loads the existing `tweets.json`, finds the most recent tweet's timestamp, and fetches only tweets posted since (latest - 5 days). The 5-day overlap window is deliberate: it covers any tweets the previous run might have missed due to X API filtering or rate limits, plus a margin for any tweets that became newly accessible (e.g., when X's filtering shifts). Newly-fetched tweets merge with the existing dataset by ID; tweets older than the start window are preserved from the prior run. The classifier is re-run over the *whole* merged set on every refresh, so trigger-list updates apply retroactively to old tweets without needing a fresh API fetch. Adds a `--full-fetch` flag for the rare case when a full re-fetch is needed (e.g., after a major classifier change that warrants re-pulling raw data). Typical daily cost falls from ~2,000 reads to ~5–50.
- **v1.3.8** (2026-05-27) — Diplomatic-protest action triggers. The v1.3.7 direct-ID lookup proved the X API was returning Wong's thread continuation tweet ("I have directed DFAT to call in Israel's Ambassador…"), but the classifier was silently dropping it — the verbs `directed` and `call in` weren't in any trigger list. Calling in an ambassador is a formal critical action that signals serious displeasure, short of recall or expulsion. v1.3.8 adds three new pattern families: **Concern tier** for `call in / called in / summon / haul in` an `ambassador / envoy / diplomat / high commissioner`; **Criticise tier** for `expel` an ambassador (theirs) or `recall (our|the|its)` ambassador (severe protest). All patterns require proximity (within 40 chars) to a diplomatic-role noun, which prevents false positives on common phrases like "called in sick" or "summoned the courage to act". Content-neutral: applies to any country in the same construction.
- **v1.3.7** (2026-05-27) — Added direct ID lookup. v1.3.6's conversation-chase still didn't surface Wong's self-replies, suggesting X applies aggressive heuristic filtering to *all* timeline-and-search-based queries that mention her account. The `/2/tweets?ids=A,B,C` endpoint bypasses this filtering entirely — it returns whatever tweets exist at those IDs, period. v1.3.7 reads a `missed_ids.json` file (just a list of tweet IDs, no text required), batch-fetches them via the IDs endpoint, and merges any results into the dataset. Tweets surfaced this way are flagged `fetched_by_id: true` in the output and rendered in the table with a blue `direct-id` badge for audit. This is also a diagnostic: if the IDs endpoint returns a tweet that no other query returned, we've proven the tweet is API-accessible — just hidden from broader queries. If the endpoint *also* doesn't return it, the tweet is genuinely beyond Basic-tier reach.
- **v1.3.6** (2026-05-27) — Conversation chasing. v1.3.5's `from:X is:reply` search query did not surface Wong's self-replies (her own follow-up tweets within a thread she started). To bypass X's filtering, the scraper now performs a third pass: for every conversation Wong started in the last 7 days, it issues an explicit `from:SenatorWong (conversation_id:A OR conversation_id:B OR …)` query, batched ~25 conversation IDs per query to stay under X's query length limit. The conversation-id filter is so specific that there is nothing for X to "filter against" — every tweet Wong made in those threads should return. Only recent (last-7-day) threads are chased because the `/2/tweets/search/recent` endpoint can't see further back than that on Basic tier; deeper history continues to rely on the timeline endpoint.
- **v1.3.5** (2026-05-27) — Thread-continuation coverage fix. v1.3.4 successfully retrieved thread *leads* (the first tweet in a multi-tweet thread) but X's search endpoint was still filtering Wong's *self-replies* (her subsequent tweets in the same thread, posted seconds after the lead). Empirically, `from:SenatorWong` returns originals and replies to other accounts but quietly drops the user's replies to herself. Fix: the search step now runs two queries in parallel, `from:SenatorWong` and `from:SenatorWong is:reply`, and merges the results by tweet ID. The explicit `is:reply` query restores thread continuations to the dataset. Also removed the redundant `-is:retweet` query suffix (retweets are filtered client-side).
- **v1.3.4** (2026-05-27) — Fixed the scraper to capture replies and thread continuations more reliably. Two changes: (1) Removed the server-side `exclude=retweets` parameter on the `/2/users/:id/tweets` endpoint, which empirical testing showed was over-filtering replies and thread leads despite documentation saying it shouldn't. Retweets are now filtered client-side by inspecting `referenced_tweets[].type` — semantically equivalent for the dataset, but the API no longer drops the surrounding context. (2) Added a parallel fetch from the `/2/tweets/search/recent` endpoint, which uses a separate filtering pipeline and frequently surfaces tweets the user-timeline endpoint omits. Results from both endpoints are merged by tweet ID. Search is limited to the last 7 days on Basic tier, so it acts as a "recent coverage booster" on top of the deep history from the timeline endpoint. Also added `\\bcalls? for\\b` and `\\b(our|the|a) call for\\b` to the Call-for-action trigger list, catching the bare verb form ("our call for the release of...") that the gerund/past patterns alone missed.
- **v1.3.3** (2026-05-26) — Acknowledged a documented limitation of the X API's `/2/users/:id/tweets` endpoint: it does not always return every tweet the account has posted, especially replies and conversation continuations. To compensate, the build pipeline now reads a `manual_tweets.json` file (schema: `{ "tweets": [{ "id", "created_at", "text", "added_by"?, "note"? }, ...] }`) and merges those tweets into the dataset, running them through the same classifier as auto-fetched tweets. Manually-added tweets are tagged in the output (`manually_added: true`) and rendered with a yellow "manual" badge in the table so readers can audit the proportion that came in by hand. The build summary also reports a separate count of manual tweets. Additionally expanded the X API request to include `tweet.fields=in_reply_to_user_id,conversation_id,author_id` and `expansions=in_reply_to_user_id,referenced_tweets.id,author_id` to maximise the auto-fetch's coverage of replies.
- **v1.3.2** (2026-05-26) — **Victim-pattern exclusion.** When a sentence describes violence done TO a country ("attacks on Israel", "killing of two Israeli embassy staff", "rocket fire on Russian diplomats", "bombing of Ukrainian cities"), the country named is the *victim* of the violence — not the target of the criticism. v1.3.2 captures the text between the violence-word and either "by …" (which names the perpetrator) or sentence-end, and strips any countries found in that span from the critical-target list for that sentence. Same shape as the co-signatory and descriptive-construction exclusions. Content-neutral: applies symmetrically to any country in the construction. Fixes the long-standing "condemns attacks on X by Y" false positive that was wrongly tagging victim X as a criticism target. Surfaced by user-flagged false positives on (a) a tweet condoling the killing of Israeli embassy staff in Washington DC and (b) a tweet condoling antisemitic attacks on Israeli soccer fans in Amsterdam — both correctly drop from the critical-target counts under v1.3.2. Also added "thoughts go out to", "shared/expressed condolences" and "shared my condolences with" as Solidarity-tier positive triggers.
- **v1.3.1** (2026-05-26) — Added Lebanon, Jordan, Egypt, UAE, Qatar, Iraq, Yemen, and Libya to the country target list (closes Middle East coverage gap). Added "Hizballah" spelling variant. Added two new families of Concern-tier patterns:
  - *Diplomatic restraint* — "calls on X to exercise restraint", "urges the exercise of restraint", "show/maximum/utmost restraint".
  - *"How X defends itself matters" / "manner in which X defends"* — diplomatic soft-criticism that grants the right to act while flagging the manner as a concern. Same register as "restraint". Content-neutral pattern, though in current diplomatic usage the phrase is used overwhelmingly about Israel — a fact about how the phrase circulates, not about how the rule fires. The rule would fire identically on the same construction directed at any other named country.

  Added descriptive-construction exclusion: country names appearing in attributive phrases like "Indonesian-funded hospital", "Jordanian field hospital", "Iranian-backed militia" are stripped from target lists for the sentence they appear in, because those constructions describe a noun's funding/origin/operation, not the statement's target. Same shape as the v1.3 co-signatory exclusion. Honest consequence: some tweets that v1.3 mis-tagged as critical of country X (because X was named only descriptively) are now correctly classified as having no identifiable country target and are excluded from the dataset.
- **v1.3** (2026-05-26) — Broadened the Call-for-action trigger list to capture grammatical forms missed in v1.2. Specifically, the v1.2 patterns only fired on "call on / calls on X to" and the strict "urge X to" form, missing "**calling** on" (gerund), "called on" (past), "calling for", "urging X to", "urge **all parties** to" (multi-word target), and passive constructions like "must be allowed/protected/guaranteed/ensured" and "aid must flow / immediate ceasefire / unimpeded access". The fix is content-neutral: the same patterns apply to all targets equally. Surfaced as a result of a noted false negative on a 2025-04-24 Israel/Gaza humanitarian statement where the call on Israel was missed and only the call on Hamas was recorded.
- **v1.2** (2026-05-25) — Added positive-statement tracking (Endorse / Commend / Appreciate / Solidarity tiers). Clarified that criticism or praise of any named cabinet minister or senior official attributes to their country (e.g. Ben-Gvir → Israel). Substantially expanded the country list to include allies and partners. Introduced sentence-level tone scoping.
- **v1.0** (initial) — Critical-only tracker with four severity tiers.

**Methodology version:** 1.3
**Last updated:** 2026-05-26
