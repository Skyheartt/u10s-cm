# U10S CM

Static leaderboard of champion medals on the 700 Everios U10S maps.

The site is the `web` folder. Favorites stay in the browser (`localStorage`). A Python script reads the Nadeo leaderboards and writes `web/data/standings.json`.

A full pass takes about 18 minutes: 950 leaderboard requests at one per second. The script refuses to run again when the published file is under 30 minutes old, so the hourly job is not skipped. That is the fastest pace that still leaves the API idle most of the hour.

## Run it locally

1. Copy `.env.example` to `.env` and fill in the four credentials plus a contact address.
2. `python scripts/refresh.py`
3. `python -m http.server 4173 -d web`
4. Open `http://127.0.0.1:4173`

`python scripts/refresh.py --resolve-only` only matches map names to Trackmania Exchange ids and does not call Nadeo.

## Credentials

Use a spare Ubisoft account. A ban or a rate limit on the account that calls the API would also hit the account you play on if they are the same.

Service account, for the leaderboards:

1. Sign in at <https://www.trackmania.com/player/service-accounts> with the spare account.
2. Create the service account and store the password. It is shown only once.
3. Put that login and password in `NADEO_LOGIN` and `NADEO_PASSWORD`.

OAuth application, for display names:

1. Sign in at <https://api.trackmania.com> with the same spare account.
2. Create an application. Copy the Identifier and the Secret.
3. Put them in `TM_CLIENT_ID` and `TM_CLIENT_SECRET`.

Do not commit `.env`.

## Hosting

The pages are free on Cloudflare Pages. Only the domain `u10s-cm.fr` costs money. A Hostinger web-hosting plan is unnecessary.

1. Create a public GitHub repository and push this folder.
2. In the repository settings, add Actions secrets: `NADEO_LOGIN`, `NADEO_PASSWORD`, `TM_CLIENT_ID`, `TM_CLIENT_SECRET`, `CONTACT`.
3. Run the "Refresh leaderboard" workflow once, from the Actions tab. Later runs are hourly.
4. On Cloudflare, create a Pages project from the repository. Build command: empty. Output directory: `web`.
5. Add the custom domain `u10s-cm.fr`.
6. At the registrar, point the domain at the Cloudflare nameservers Pages shows you. Hostinger can stay the registrar.
