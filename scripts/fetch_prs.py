import os
import csv
import requests
from dateutil import parser

# --- Configuration ---
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
PUBLIC_REPO_OWNER = os.environ.get("PUBLIC_REPO_OWNER")
PUBLIC_REPO_NAME = os.environ.get("PUBLIC_REPO_NAME")
DATE_RANGE = os.environ.get("DATE_RANGE")
OUTPUT_CSV = "prs.csv"
API_URL = "https://api.github.com/graphql"

if not GITHUB_TOKEN:
    print("GITHUB_TOKEN environment variable is required.")
    exit(1)

HEADERS = {"Authorization": f"Bearer {GITHUB_TOKEN}"}

PR_QUERY = '''
query($searchQuery: String!, $cursor: String) {
  search(query: $searchQuery, type: ISSUE, first: 50, after: $cursor) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        ... on PullRequest {
          number
          title
          author {
            login
          }
          state
          createdAt
          mergedAt
          closedAt
          merged
          timelineItems(itemTypes: [PULL_REQUEST_REVIEW], first: 100) {
            nodes {
              __typename
              ... on PullRequestReview {
                author {
                  login
                }
                state
                submittedAt
              }
            }
          }
        }
      }
    }
  }
}
'''


def hours_between(d1, d2):
    if not d1 or not d2:
        return None
    return int((d2 - d1).total_seconds() / 60)


def fetch_all_prs():
    prs = []
    cursor = None
    while True:
        search_query_string = f"repo:{PUBLIC_REPO_OWNER}/{PUBLIC_REPO_NAME} is:pr is:public created:{DATE_RANGE}"

        # 3. 准备发送到API的变量
        variables = {
            "searchQuery": search_query_string,
            "cursor": cursor  # or the actual cursor for pagination
        }
        resp = requests.post(API_URL, json={"query": PR_QUERY, "variables": variables}, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
        pr_nodes = data['data']['search']['edges']
        prs.extend(pr_nodes)
        page = data['data']['search']['pageInfo']
        if not page['hasNextPage']:
            break
        cursor = page['endCursor']
    return prs

def process_pr(pr):
    created_at = parser.isoparse(pr['createdAt'])
    merged_at = parser.isoparse(pr['mergedAt']) if pr['mergedAt'] else None
    author = pr['author']['login'] if pr['author'] else None
    # Find first review by non-author
    first_review_at = None
    first_approval_at = None
    for node in pr['timelineItems']['nodes']:
        if node['__typename'] == 'PullRequestReview':
            reviewer = node['author']['login'] if node['author'] else None
            if reviewer and reviewer != author:
                if not first_review_at:
                    first_review_at = parser.isoparse(node['submittedAt'])
                if node['state'] == 'APPROVED' and not first_approval_at:
                    first_approval_at = parser.isoparse(node['submittedAt'])
        elif node['__typename'] == 'ReviewedEvent':
            reviewer = node['actor']['login'] if node['actor'] else None
            if reviewer and reviewer != author and not first_review_at:
                first_review_at = parser.isoparse(node['createdAt'])
        if first_review_at is not None and first_approval_at is not None:
            break
    # Calculate intervals
    t1 = hours_between(created_at, first_review_at)
    t2 = hours_between(first_review_at, first_approval_at)
    t3 = hours_between(first_approval_at, merged_at)
    was_merged = 1 if pr['state'] == 'MERGED' else 0
    return {
        'pr_number': pr['number'],
        'time_to_first_review_sec': t1 if t1 is not None else '',
        'time_to_approval_sec': t2 if t2 is not None else '',
        'time_to_merge_sec': t3 if t3 is not None else '',
        'was_merged': was_merged
    }

def main():
    prs = fetch_all_prs()
    rows = []
    for pr in prs:
        row = process_pr(pr['node'])
        rows.append(row)
    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['pr_number', 'time_to_first_review_sec', 'time_to_approval_sec',
                                               'time_to_merge_sec', 'was_merged'])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} PRs to {OUTPUT_CSV}")

if __name__ == '__main__':
    main()
