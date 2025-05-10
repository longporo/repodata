#!/usr/bin/env python3
import os
import requests
import csv
import json
import sys
from datetime import datetime, timedelta, timezone

# --- Configuration ---
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
PUBLIC_REPO_OWNER = os.environ.get("PUBLIC_REPO_OWNER")
PUBLIC_REPO_NAME = os.environ.get("PUBLIC_REPO_NAME")
SINCE_DATE_ISO = os.environ.get("SINCE_DATE")
OUTPUT_CSV = "issues.csv"
API_URL = "https://api.github.com/graphql"
ISSUES_PER_PAGE = 100
PR_COMMITS_PER_PAGE = 100

# --- Input Validation ---
if not GITHUB_TOKEN:
    print("Error: GITHUB_TOKEN environment variable not set.", file=sys.stderr)
    sys.exit(1)
if not SINCE_DATE_ISO:
    print("Error: SINCE_DATE environment variable not set.", file=sys.stderr)
    sys.exit(1)

# --- Helper Functions ---
def run_graphql_query(query, variables={}):
    """Executes a GraphQL query against the GitHub API."""
    headers = {"Authorization": f"bearer {GITHUB_TOKEN}"}
    try:
        response = requests.post(
            API_URL,
            headers=headers,
            json={"query": query, "variables": variables}
        )
        response.raise_for_status()
        resp_json = response.json()
        # Check for GraphQL-level errors
        if "errors" in resp_json:
            print(f"GraphQL Error: {resp_json['errors']}", file=sys.stderr)
        return resp_json
    except requests.exceptions.RequestException as e:
        print(f"Error executing GraphQL query: {e}", file=sys.stderr)
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}", file=sys.stderr)
            print(f"Response text: {e.response.text}", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response: {e}", file=sys.stderr)
        print(f"Response text: {response.text}", file=sys.stderr) # Use response from outer scope
        return None

def get_author_name(author_data):
    """Extracts the best available author identifier from commit author nodes."""
    if not author_data: return None
    user = author_data.get("user")
    if user and user.get("login"):
        return user["login"]
    if author_data.get("name"):
        return author_data["name"]
    return None

# --- GraphQL Queries ---

# Stage 1: Fetch Issues and identify linked PRs via timeline
FETCH_ISSUES_QUERY = """
query($owner: String!, $name: String!, $since: DateTime!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(
      first: %d, # Issues per page
      after: $cursor,
      filterBy: {since: $since},
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      pageInfo {
        endCursor
        hasNextPage
      }
      nodes {
        id
        number
        title
        state
        createdAt
        closedAt
        # Find PRs linked via timeline (ClosedEvent closer or CrossRef source)
        timelineItems(itemTypes: [CLOSED_EVENT, CROSS_REFERENCED_EVENT], first: 20) { # Limit timeline check per issue
          nodes {
            __typename
            ... on ClosedEvent {
              closer {
                 __typename
                ... on PullRequest {
                  number
                  repository { nameWithOwner } # Get owner/name
                }
              }
            }
            ... on CrossReferencedEvent {
               source {
                 __typename
                ... on PullRequest {
                  number
                  repository { nameWithOwner } # Get owner/name
                }
              }
            }
          }
        }
      }
    }
  }
}
""" % ISSUES_PER_PAGE # Inject page size into query string

# Stage 2: Fetch commits for a specific PR
FETCH_PR_COMMITS_QUERY = """
query($owner: String!, $name: String!, $prNumber: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $prNumber) {
      commits(first: %d, after: $cursor) { # Commits per page
        pageInfo {
          endCursor
          hasNextPage
        }
        nodes {
          commit {
            author {
              user { login }
              name
              # email # Not fetching email by default
            }
          }
        }
      }
    }
  }
}
""" % PR_COMMITS_PER_PAGE # Inject page size

# --- Stage 1: Fetch Issues and Identify Linked PRs ---
def fetch_issues_and_identify_prs(target_owner, target_name, since_iso):
    all_issues_raw_data = [] # Store {issue_details, linked_pr_keys_set}
    unique_pr_keys = set() # Store unique (owner, name, number) tuples
    issues_cursor = None
    issues_has_next_page = True

    print(f"Stage 1: Fetching issues updated since {since_iso} from {target_owner}/{target_name}...")

    while issues_has_next_page:
        print(f"  Fetching issues page (cursor: {issues_cursor})...")
        variables = {
            "owner": target_owner,
            "name": target_name,
            "since": since_iso,
            "cursor": issues_cursor
        }
        response = run_graphql_query(FETCH_ISSUES_QUERY, variables)

        if not response or response.get("data") is None:
            print(f"  Error fetching issues or empty data received. Stopping issue fetch.", file=sys.stderr)
            break # Stop if the query failed or returned no data structure

        repo_data = response.get("data", {}).get("repository")
        if not repo_data or not repo_data.get("issues"):
            print(f"  Could not find repository/issues data in response. Skipping page.", file=sys.stderr)
            issues_has_next_page = False
            continue

        issues = repo_data["issues"]["nodes"]
        page_info = repo_data["issues"]["pageInfo"]
        issues_has_next_page = page_info.get("hasNextPage", False)
        issues_cursor = page_info.get("endCursor")

        print(f"  Fetched {len(issues)} issues on this page.")

        for issue in issues:
            if not issue: continue
            linked_pr_keys_for_issue = set()
            timeline_items = issue.get("timelineItems", {}).get("nodes", [])

            for item in timeline_items:
                pr_info = None
                # Check ClosedEvent closer
                if item and item.get("__typename") == "ClosedEvent":
                    closer = item.get("closer")
                    if closer and closer.get("__typename") == "PullRequest":
                        pr_info = closer
                # Check CrossReferencedEvent source
                elif item and item.get("__typename") == "CrossReferencedEvent":
                    source = item.get("source")
                    if source and source.get("__typename") == "PullRequest":
                        pr_info = source

                # If a PR was found, store its identifier
                if pr_info and pr_info.get("repository") and pr_info.get("number"):
                    repo_full_name = pr_info["repository"]["nameWithOwner"]
                    pr_number = pr_info["number"]
                    try:
                        pr_owner, pr_name = repo_full_name.split('/')
                        pr_key = (pr_owner, pr_name, pr_number)
                        linked_pr_keys_for_issue.add(pr_key)
                        unique_pr_keys.add(pr_key)
                    except ValueError:
                        print(f"  Warning: Could not parse owner/name from {repo_full_name} for PR #{pr_number} linked to issue #{issue['number']}", file=sys.stderr)

            # Store raw issue data along with the set of linked PR keys
            all_issues_raw_data.append({
                "details": issue,
                "linked_pr_keys": linked_pr_keys_for_issue
            })

        if not issues_has_next_page:
            print(f"  No more issues pages.")
            break

    print(f"Stage 1 Complete: Identified {len(all_issues_raw_data)} relevant issues and {len(unique_pr_keys)} unique linked PRs.")
    return all_issues_raw_data, unique_pr_keys

# --- Stage 2: Fetch Commits for Unique PRs ---
def fetch_authors_for_prs(pr_keys):
    pr_author_map = {} # { pr_key: set(authors) }
    total_prs = len(pr_keys)
    print(f"Stage 2: Fetching commit authors for {total_prs} unique PRs...")

    for i, pr_key in enumerate(pr_keys, 1):
        pr_owner, pr_name, pr_number = pr_key
        print(f"  Processing PR {i}/{total_prs}: {pr_owner}/{pr_name}#{pr_number}")
        pr_authors = set()
        commits_cursor = None
        commits_has_next_page = True

        while commits_has_next_page:
            variables = {
                "owner": pr_owner,
                "name": pr_name,
                "prNumber": pr_number,
                "cursor": commits_cursor
            }
            response = run_graphql_query(FETCH_PR_COMMITS_QUERY, variables)

            if not response or response.get("data") is None:
                print(f"    Error fetching commits for PR {pr_key}. Skipping.", file=sys.stderr)
                commits_has_next_page = False # Stop trying for this PR
                continue

            pr_data = response.get("data", {}).get("repository", {}).get("pullRequest")
            if not pr_data or not pr_data.get("commits"):
                commits_has_next_page = False
                continue

            commits = pr_data["commits"]["nodes"]
            page_info = pr_data["commits"]["pageInfo"]
            commits_has_next_page = page_info.get("hasNextPage", False)
            commits_cursor = page_info.get("endCursor")

            for commit_node in commits:
                if not commit_node or not commit_node.get("commit"): continue
                author_info = commit_node["commit"].get("author", {})
                name = get_author_name(author_info)
                if name:
                    pr_authors.add(name)

            if not commits_has_next_page:
                pass

        pr_author_map[pr_key] = pr_authors
        print(f"  -> Found {len(pr_authors)} unique authors for PR {pr_key}")


    print(f"Stage 2 Complete: Processed authors for {len(pr_author_map)} PRs.")
    return pr_author_map

# --- Stage 3: Aggregate and Write CSV ---
def aggregate_and_write_csv(issues_raw_data, pr_author_map, output_file):
    print(f"Stage 3: Aggregating contributors and writing to {output_file}...")
    final_data_for_csv = []

    for issue_data in issues_raw_data:
        issue_details = issue_data["details"]
        linked_pr_keys = issue_data["linked_pr_keys"]
        issue_contributors = set()

        for pr_key in linked_pr_keys:
            authors = pr_author_map.get(pr_key, set()) # Get authors for this PR
            issue_contributors.update(authors) # Add them to the issue's set

        final_data_for_csv.append([
            issue_details.get("id"),
            issue_details.get("number"),
            issue_details.get("title"),
            issue_details.get("state"),
            issue_details.get("createdAt"),
            issue_details.get("closedAt") or "", # Use empty string if null
            ";".join(sorted(list(issue_contributors))) # Join unique names
        ])

    print(f"  Aggregated data for {len(final_data_for_csv)} issues.")

    # --- Write CSV using Python's csv module ---
    try:
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            # Write Header
            writer.writerow(["issue_id", "issue_number", "title", "state", "created_date", "closed_date", "contributors"])
            # Write Data Rows
            writer.writerows(final_data_for_csv)
        print(f"Successfully wrote CSV data to {output_file}")
    except IOError as e:
        print(f"Error writing CSV file {output_file}: {e}", file=sys.stderr)
        sys.exit(1)


# --- Main Execution ---
if __name__ == "__main__":
    print("Starting multi-stage contributor fetch process...")

    # Stage 1
    issues_raw, unique_prs = fetch_issues_and_identify_prs(
        PUBLIC_REPO_OWNER, PUBLIC_REPO_NAME, SINCE_DATE_ISO
    )

    # Stage 2
    pr_authors = fetch_authors_for_prs(unique_prs)

    # Stage 3
    aggregate_and_write_csv(issues_raw, pr_authors, OUTPUT_CSV)

    print("Process completed!")