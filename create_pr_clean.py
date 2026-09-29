import os
import requests
import json

API_KEY = os.environ.get("GITHUB_TOKEN")
headers = {"Authorization": f"Bearer {API_KEY}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

r = os.popen("git rev-parse HEAD").read().strip()
branch_name = "jules-clean-docs-final"

print(f"Creating remote branch {branch_name} from SHA {r}...")
res = requests.post("https://api.github.com/repos/aafricawala/schwab-marketdata-pilot/git/refs", headers=headers, json={"ref":f"refs/heads/{branch_name}", "sha": r})

if res.status_code == 201 or "Reference already exists" in res.text:
    print("Branch is ready.")
    url = f"https://api.github.com/repos/aafricawala/schwab-marketdata-pilot/pulls"
    data = {
        "title": "Finalize manual line-by-line documentation (Clean Reset)",
        "head": branch_name,
        "base": "main",
        "body": "This PR contains the finalized line-by-line documentation for the remaining files. It is branched cleanly off `main` to completely bypass all previous merge conflicts."
    }
    pr_res = requests.post(url, headers=headers, json=data)
    if pr_res.status_code == 201:
        pr_url = pr_res.json()["html_url"]
        print(f"SUCCESS: Created Pull Request: {pr_url}")
    else:
        print(f"Failed to create PR: {pr_res.status_code} - {pr_res.text}")
else:
    print(f"Failed to create branch: {res.status_code} - {res.text}")
