#!/usr/bin/env python3
import os
import requests
import csv
import json
from datetime import datetime, timedelta

# --- Configuration ---
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
PUBLIC_REPO_OWNER = os.environ.get("PUBLIC_REPO_OWNER")
PUBLIC_REPO_NAME = os.environ.get("PUBLIC_REPO_NAME")
SINCE_DATE_ISO = os.environ.get("SINCE_DATE")
OUTPUT_CSV = "commits.csv"
API_URL = "https://api.github.com/graphql"
COMMITS_PER_PAGE = 100

# --- Helper Functions ---
def get_default_branch(owner, repo):
    """Gets the default branch name for the repository."""
    query = f'{{ repository(owner: "{owner}", name: "{repo}") {{ defaultBranchRef {{ name }} }} }}'
    headers = {"Authorization": f"bearer {GITHUB_TOKEN}"}
    response = requests.post(API_URL, json={'query': query}, headers=headers)
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        print("GraphQL Error fetching default branch:", data["errors"])
        return "main" # Fallback
    try:
        branch = data["data"]["repository"]["defaultBranchRef"]["name"]
        print(f"Found default branch: {branch}")
        return branch
    except (KeyError, TypeError):
        print("Could not determine default branch, defaulting to 'main'")
        return "main"

def fetch_commits_page(owner, repo, branch, since, cursor=None):
    """Fetches a single page of commits."""
    after_clause = f', after: "{cursor}"' if cursor else ""
    query = f"""
    {{
      repository(owner: "{owner}", name: "{repo}") {{
        ref(qualifiedName: "{branch}") {{
          target {{
            ... on Commit {{
              history(first: {COMMITS_PER_PAGE}, since: "{since}"{after_clause}) {{
                nodes {{
                  oid
                  messageHeadline
                  committedDate
                  changedFilesIfAvailable
                  additions
                  deletions
                  author {{
                    name
                    email
                    user {{
                      login
                    }}
                  }}
                }}
                pageInfo {{
                  endCursor
                  hasNextPage
                }}
              }}
            }}
          }}
        }}
      }}
    }}
    """
    headers = {"Authorization": f"bearer {GITHUB_TOKEN}"}
    response = requests.post(API_URL, json={'query': query}, headers=headers)
    response.raise_for_status() # Raise exception for bad status codes
    return response.json()

def get_author_name(author_data):
    """Extracts the best available author identifier."""
    if author_data.get("user") and author_data["user"].get("login"):
        return author_data["user"]["login"]
    if author_data.get("name"):
        return author_data["name"]
    if author_data.get("email"):
        return author_data["email"]
    return "Unknown"

# --- Main Execution ---
if not GITHUB_TOKEN:
    print("Error: GITHUB_TOKEN environment variable not set.")
    exit(1)
if not SINCE_DATE_ISO:
    print("Error: SINCE_DATE environment variable not set.")
    exit(1)

all_commits = []
has_next_page = True
current_cursor = None
default_branch = get_default_branch(PUBLIC_REPO_OWNER, PUBLIC_REPO_NAME)

print(f"Fetching commits since {SINCE_DATE_ISO} from {PUBLIC_REPO_OWNER}/{PUBLIC_REPO_NAME} on branch {default_branch}...")

while has_next_page:
    try:
        data = fetch_commits_page(
            PUBLIC_REPO_OWNER,
            PUBLIC_REPO_NAME,
            default_branch,
            SINCE_DATE_ISO,
            current_cursor
        )

        if "errors" in data:
            print("GraphQL Error fetching commits page:", data["errors"])
            break

        history = data.get("data", {}).get("repository", {}).get("ref", {}).get("target", {}).get("history", {})
        nodes = history.get("nodes", [])
        page_info = history.get("pageInfo", {})

        if not nodes and current_cursor is None: # Check if repository/ref/target is null on first fetch
             if not data.get("data", {}).get("repository", {}).get("ref", {}):
                  print("Warning: Repository or ref not found, or history is empty.")
             elif not data.get("data", {}).get("repository", {}).get("ref", {}).get("target"):
                  print(f"Warning: Target (commit history) for branch '{default_branch}' not found. Branch might be empty or incorrect.")
             else:
                 print("No commits found for the specified period.")
             break


        for commit in nodes:
            author = commit.get("author", {})
            author_name = get_author_name(author)
            diff = commit.get("additions", 0) + commit.get("deletions", 0)
            all_commits.append([
                commit.get("oid"),
                commit.get("messageHeadline"),
                commit.get("committedDate"),
                commit.get("changedFilesIfAvailable", 0), # Provide default if missing
                diff,
                author_name
            ])

        has_next_page = page_info.get("hasNextPage", False)
        current_cursor = page_info.get("endCursor")

        print(f"Fetched {len(nodes)} commits... Has next page: {has_next_page}")
        if not has_next_page:
            print("Reached end of commit history for the period.")

    except requests.exceptions.RequestException as e:
        print(f"HTTP Request failed: {e}")
        break
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        break

# --- Write CSV ---
print(f"Writing {len(all_commits)} commits to {OUTPUT_CSV}...")
try:
    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["sha", "message", "created_date", "number_of_files_updated", "diff", "author"])
        writer.writerows(all_commits)
    print("Successfully wrote commits.csv")
except IOError as e:
    print(f"Error writing CSV file: {e}")
    exit(1) 