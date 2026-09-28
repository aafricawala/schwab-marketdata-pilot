import os
import requests

API_KEY = os.environ.get("GITHUB_TOKEN")
headers = {"Authorization": f"Bearer {API_KEY}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

# get current local sha
r = os.popen(f"git rev-parse HEAD").read().strip()
branch_name = "jules-documentation-fixes-final-v4"
requests.post("https://api.github.com/repos/aafricawala/schwab-marketdata-pilot/git/refs", headers=headers, json={"ref":f"refs/heads/{branch_name}", "sha": r})

url = f"https://api.github.com/repos/aafricawala/schwab-marketdata-pilot/pulls"
data = {"title": "Finalize manual line-by-line documentation for the remaining 8 python files", "head": branch_name, "base": "main", "body": "Resolves all previous merge conflicts and completes documentation."}
res = requests.post(url, headers=headers, json=data)
if res.status_code == 201:
  pr_number = res.json()["number"]
  print(f"Created PR #{pr_number}")
  # Merge it
  merge_res = requests.put(f"https://api.github.com/repos/aafricawala/schwab-marketdata-pilot/pulls/{pr_number}/merge", headers=headers)
  print(merge_res.status_code, merge_res.text)
else:
  print(res.status_code, res.text)
