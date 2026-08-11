# coetoday.sg

Static COE price tracker. Same pipeline pattern as resaleshdb.

## Deploy checklist
1. Open scripts/fetch_coe.py — set DATASET_ID (search "COE bidding results" on data.gov.sg, verify CSV column names against the script's CAT_MAP/fields).
2. Push to GitHub, run the "Update COE data" workflow manually once (Actions tab → workflow_dispatch) to replace the seed data with full history.
3. Link repo to Netlify: publish dir = root, no build command.
4. Point coetoday.sg DNS at Netlify.
5. Paste GA4 snippet into index.html (marked comment near </body>).
6. Submit to Google Search Console + request indexing.

## Ad placements (fixed, shown to buyers)
- Slot 1: leaderboard under results board (728x90 / 320x100)
- Slot 2: medium rectangle mid-content (300x250 / 336x280)
- Slot 3: footer band (970x90 / responsive)
