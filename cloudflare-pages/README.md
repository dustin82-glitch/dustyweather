Cloudflare Pages Frontend

This folder is a cloud-hosted version of your local ESP page.

What it does:
- Keeps the same table and gauge layout as local.
- Reads live data from your Worker API instead of local slash data.

Before deploy:
1. Open index.html and set API_BASE to your Worker URL if it changes.
2. Set API_DEVICE_ID to your station device id if needed.

Deploy on Cloudflare Pages:
1. Cloudflare dashboard, Workers and Pages, Create, Pages.
2. Use Direct Upload.
3. Upload the files in this folder.
4. Open the Pages URL to view your cloud dashboard.

Notes:
- This page calls GET /api/latest every 2 seconds.
- If your API includes extra fields later such as wind direction or gust, the page will show them when present.

GitHub Auto-Deploy Setup (recommended):
1. In Cloudflare, create a Pages project name you want to use (for example: dustyweather).
2. In Cloudflare, create your D1 database and copy its Database ID.
3. Open cloudflare-pages/wrangler.toml and replace REPLACE_WITH_D1_DATABASE_ID.
4. In your GitHub repo, add these repository secrets:
	- CLOUDFLARE_API_TOKEN
	- CLOUDFLARE_ACCOUNT_ID
	- CLOUDFLARE_PAGES_PROJECT_NAME
5. API token permissions should include:
	- Account, Cloudflare Pages, Edit
	- Account, Workers Scripts, Edit
	- Account, D1, Edit (or needed D1 access)
6. Commit and push. The workflow at .github/workflows/deploy-cloudflare.yml deploys both Worker and Pages on push to main.
