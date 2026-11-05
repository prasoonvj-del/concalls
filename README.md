# Market Desk: concall summaries and a morning news brief

## ★ The fully automatic website (recommended)
Every morning, GitHub runs this tool on its own servers, so your laptop and tablet can stay off. Each run:
1. reads your RSS feeds and builds the **morning brief**: the big picture, the top stories explained (context, why it matters, what to watch), sector mood and news-flow charts, and the most-mentioned companies;
2. summarises **new concall transcripts** from BSE, compares each with the previous quarter, and writes sector overviews;
3. publishes everything to **one website**, for example `https://prasoonvj-del.github.io/concalls/`. Open it on any device; on the tablet use Chrome → ⋮ → **Add to Home screen** and it opens like an app.

**One-time setup on github.com:**
1. **Keys.** In your `concalls` repository, go to **Settings → Secrets and variables → Actions → New repository secret** and add two secrets:
   - `GEMINI_API_KEY`: your Gemini key
   - `GROQ_API_KEY`: your Groq key (optional, but it keeps the run going when Gemini is busy)

   Secrets are encrypted. They never appear in the code or on the website.
2. **Website.** Go to **Settings → Pages → Build and deployment → Source** and choose **GitHub Actions**.
3. **First run.** Go to **Actions → Daily update → Run workflow**. The first run takes 30–60 minutes, because it also goes back 150 days for concalls. After that it runs by itself every morning at about 5:10 am and takes 15–30 minutes.

**Good to know**
- The repository and the website are public. That's what GitHub's free plan allows, and everything on them comes from public news and BSE filings. Your API keys stay secret, and your **watchlist** is kept only in your browser (⚙ on the website), so it's never published.
- Each run summarises up to 30 new concalls, so it stays inside the free AI limits. In busy results weeks the rest carry over to the next day. You can change this in `config.ini` under `[cloud]`.
- To refresh during the day, go to **Actions → Daily update → Run workflow**.
- To change your feeds, export a new OPML from FeedFlow and replace `feeds.opml` in the repository: **Add file → Upload files**.

---

# Running it yourself (laptop or tablet)

This tool downloads earnings-call transcripts from BSE and writes an AI summary of each one (key numbers, guidance, demand, margins, capex, risks, notable analyst Q&A). When you summarise a sector, it also writes an overview of what managements across that sector are saying.

## Setup (once)
1. Unzip this folder to `E:\ConcallSummaries`. You can delete the old ConcallDigest folder.
2. Double-click **setup.bat**.
3. Get a free key from https://aistudio.google.com/apikey: sign in with Google, click **Create API key**, and copy it.
4. Open **config.ini** in Notepad and paste the key after `api_key = `, then save.

## Use
Double-click **Concall Summaries.bat**. A menu opens:

1. **Test the AI connection.** Always do this first. It should say SUCCESS within about 10 seconds. If it doesn't, it prints the exact problem.
2. **Download the latest transcript list from BSE.** Keep the default 150 days, so last quarter's calls are included for the comparison. It's quick, because the PDFs are only downloaded when they're needed.
3. **Summarise.** Pick a whole sector, or search for particular companies by name.
   - The first time you pick a sector, the AI sorts all companies into sectors. This happens once and is saved.
   - While each summary is being written you'll see a live counter ("waiting ... 35s"). A summary usually takes 20 to 90 seconds.
   - You can stop at any time with Ctrl+C. Finished summaries are kept, and the next run carries on from where it stopped.
4. **Open the summaries page.** This is one page with every summary. You can filter by sector and quarter and search for any word.

Each summary is also saved as its own file in `summaries\<Sector>\`, named like `Trident Ltd - Q2 FY27.md`. These are plain-text Markdown files that open in Notepad or any Markdown app. Each sector folder also has a `_SECTOR OVERVIEW` file.

## If the AI test fails
- **"Key rejected"**: the key is wrong. Copy it again from AI Studio.
- **"No reply ... after Ns"**: your network, antivirus or firewall may be blocking Google's AI service. Try another network (for example a phone hotspot) to check. If it works there, the block is on your usual network.
- **Gemini keeps failing**: set up the backup AI described below, so the run keeps going when Gemini is busy.

## Backup AI (recommended, 5 minutes)
When Gemini is busy or down, the tool can switch to **Groq** by itself. Groq is free and needs no card.
1. Sign up at https://console.groq.com and go to **API Keys → Create API Key**.
2. Paste the key into `config.ini` under `[backup]`, after `api_key = `.
3. Run menu option 1. It tests both the main AI and the backup.

Groq's free tier only takes about 8,000 tokens a minute, which is less than a full transcript. So when Groq is doing the work, the tool reads each transcript in parts and then writes the summary from its notes. That takes about 3–4 minutes per company instead of under 1, but the run keeps going instead of stopping. After 15 minutes the tool tries Gemini again.

## What's in each summary
- **What changed vs last quarter.** Guidance raised, cut or kept (old vs new numbers), how the tone shifted, new or vanished risks, and whether last quarter's promises were delivered. For this, download with the default 150-day look-back so last quarter's calls are in your library. The first time you run a sector, the tool also summarises each company's previous call, about one extra AI call per company. After that it's free.
- **Figure check.** Every number in a summary is checked against the transcript. Any figure that doesn't appear word-for-word is highlighted with a **⚠ to check** badge. Usually these are growth rates the AI worked out itself, but occasionally they're misreadings, so check them in the PDF before relying on them.
- **Less noise.** Disclaimers, operator instructions and repeated page headers are removed before the transcript goes to the AI.

**Limits:** the free Gemini tier caps how many requests you can make per minute and per day. When the per-minute limit is hit, the tool counts down and resumes by itself. When the daily limit is used up, it stops and tells you; run it again the next day.

**Scanned transcripts:** a few companies file scanned image PDFs. These are skipped, with a note telling you to read the PDF on BSE.

## Run it on your tablet (Termux)
This works the same way as TradeCharts. The tool runs entirely on the tablet, so it doesn't need the laptop.

**One-time setup**
1. **Copy the whole `E:\ConcallSummaries` folder** to the tablet's **Download** folder, using USB, Google Drive or Quick Share. Copying the whole folder brings your keys (`config.ini`) and all existing summaries with it.
2. In Termux, run `termux-setup-storage` and allow access to files. Skip this if you already did it for TradeCharts.
3. Run:
   ```
   bash ~/storage/shared/Download/ConcallSummaries/setup_tablet.sh
   ```
4. Close Termux and open it again.

**Use:** type `concalls` in Termux. If you have the **Termux:Widget** app, you can instead tap the "Concall Summaries" shortcut on your home screen. The menu is the same as on the laptop.
- **Option 4** opens the summaries page in Chrome. It stays available while the menu is open.
- **Long runs:** the tool stops Android from pausing it while the screen is off. If a run still stops, go to Android Settings → Apps → Termux → Battery and set it to **No restrictions**.

**Updating later:** copy the new `concalls.py` into `Download/ConcallSummaries` and run the setup command again. Your settings and summaries on the tablet are never overwritten.

**Laptop and tablet keep separate libraries.** A summary made on one doesn't appear on the other. To bring the tablet's summaries back to the laptop, copy the tablet's `~/ConcallSummaries` folder back.

**BSE on the tablet:** on the laptop, BSE is reached through the `curl_cffi` library, which doesn't install on Android. On the tablet the tool uses the `curl` program instead. If option 2 on the tablet says "BSE refused the connection", tell Claude.


## Morning news brief (from your RSS feeds)
This reads your FeedFlow feeds (`feeds.opml`) and builds one page covering the last 24 hours:
- **The big picture.** The themes that matter today, the market mood, stocks in focus, and what to watch.
- **Your watchlist.** Every story on the companies you list under `[news]` → `watchlist` in config.ini.
- **One section per sector or topic** (Banks, Autos, Economy & Policy, Commodities, Global markets…), each with what's happening, company news, and positive and negative signals. Every point has small numbered links to the original articles.
- **Companies in the news.** Every company mentioned, with its stories.
- **Feeds that didn't load.** Useful for cleaning up dead feeds in FeedFlow.

The same story carried by several papers is merged into one, with links to every outlet that covered it. Folders that aren't market news (Sports, Tech, Financial History) are skipped; you can change this in config.ini.

**Run it:** menu **option 5** (10–20 minutes), then **option 6** to reopen the latest brief. On the tablet you can also type `brief`, or tap the "Morning Brief" Termux widget. Briefs are saved in the `news` folder; the last month is kept.

**Every morning automatically (tablet):** run `bash ~/ConcallSummaries/schedule_tablet.sh` once. The brief is then built daily at 6:30 am; for a different time, use for example `bash ~/ConcallSummaries/schedule_tablet.sh 7:15`. Termux has to stay running in the background, with its battery setting at "No restrictions". Install the Termux:API app if you'd like a notification when the brief is ready.

**Good to know**
- **Most feeds carry only a headline and a line or two.** The brief summarises what was reported; it doesn't add details the feeds didn't carry.
- **It uses about 30–40 AI requests per run,** well inside Gemini's free daily limit. If Gemini is busy, the Groq backup takes over, which is slower because big sections are written in parts.
- **To update your feed list:** export again from FeedFlow. On the tablet the newest export in Download is used automatically; on the laptop, save it in this folder as `feeds.opml`.
