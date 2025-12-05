import argparse
import sys
import copy
import re
import csv
import time

import requests
from veracode_api_signing.plugin_requests import RequestsAuthPluginVeracodeHMAC

API_HOST = "https://api.veracode.com"
APPS_URL = f"{API_HOST}/appsec/v1/applications"
BU_URL = f"{API_HOST}/api/authn/v2/business_units"
PAGE_SIZE = 500
DEFAULT_CSV = "dry_run_bu_assignments.csv"

MAX_RETRIES = 3
REQUEST_TIMEOUT = 30


def build_session():
    # session w/ HMAC signing for all calls
    s = requests.Session()
    s.auth = RequestsAuthPluginVeracodeHMAC()
    return s


def send_request(session, method, url, **kwargs):
    # simple retry logic
    if "timeout" not in kwargs:
        kwargs["timeout"] = REQUEST_TIMEOUT

    last_exc = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return session.request(method, url, **kwargs)
        except requests.RequestException as e:
            last_exc = e
            if attempt == MAX_RETRIES:
                raise
            print(f"[WARN] request failed on {url} (attempt {attempt})")
            time.sleep(attempt)

    raise last_exc or RuntimeError(f"max retries exceeded for {method} {url}")


def extract_bu_name(app_name):
    # first 4 letters before '-' define the BU name
    match = re.match(r"^([A-Za-z]{4})-", app_name)
    return match.group(1) if match else None


def fetch_all_apps(session):
    # pull all applications via simple paging
    apps = []
    page = 0

    while True:
        r = send_request(
            session,
            "GET",
            APPS_URL,
            params={"page": page, "size": PAGE_SIZE},
        )
        r.raise_for_status()

        chunk = r.json().get("_embedded", {}).get("applications", [])
        if not chunk:
            break

        apps.extend(chunk)
        page += 1

    return apps


def fetch_business_units(session):
    # fetch all BUs and map name -> guid
    result = {}
    page = 0

    while True:
        r = send_request(
            session,
            "GET",
            BU_URL,
            params={"page": page, "size": PAGE_SIZE},
        )
        try:
            r.raise_for_status()
        except requests.HTTPError:
            print("[ERROR] failed to fetch business units")
            print("status:", r.status_code)
            print("body:", r.text)
            raise

        data = r.json()
        bu_list = data.get("business_units") or data.get("_embedded", {}).get("business_units", [])

        if not bu_list:
            break

        for bu in bu_list:
            name = bu.get("bu_name")
            href = bu.get("_links", {}).get("self", {}).get("href", "")
            guid = href.rstrip("/").split("/")[-1]
            if name and guid:
                result[name] = guid

        page += 1

    return result


def create_business_unit(session, bu_name, dry_run=False):
    # create BU if missing (or simulate)
    if dry_run:
        print(f"[DRY-RUN] create BU '{bu_name}'")
        return f"{bu_name}_DRYRUN"

    r = send_request(session, "POST", BU_URL, json={"bu_name": bu_name})
    r.raise_for_status()

    href = r.json().get("_links", {}).get("self", {}).get("href", "")
    bu_guid = href.rstrip("/").split("/")[-1]
    print(f"[OK] created BU '{bu_name}'")
    return bu_guid


def get_app_details(session, app_guid):
    # retrieve full app profile before updating
    url = f"{APPS_URL}/{app_guid}"
    r = send_request(session, "GET", url)
    r.raise_for_status()
    return r.json()


def update_app_business_unit(session, app_name, app_guid, full_app, bu_name, bu_guid, dry_run=False):
    # patch app profile with correct BU assignment
    profile = copy.deepcopy(full_app.get("profile", {}))
    profile["business_unit"] = {"guid": bu_guid}
    payload = {"profile": profile}

    if dry_run:
        print(f"[DRY-RUN] assign '{app_name}' to BU '{bu_name}'")
        return

    url = f"{APPS_URL}/{app_guid}"
    r = send_request(session, "PUT", url, json=payload)
    r.raise_for_status()
    print(f"[OK] assigned '{app_name}' to BU '{bu_name}'")


def write_dry_run_csv(rows):
    # record all dry-run operations for review
    if not rows:
        print("[INFO] no rows to write")
        return

    fieldnames = [
        "app_name",
        "app_guid",
        "bu_name",
        "current_bu_guid",
        "target_bu_guid",
        "bu_action",
        "app_action",
    ]

    with open(DEFAULT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[INFO] wrote CSV: {DEFAULT_CSV} ({len(rows)} rows)")


def process_apps(dry_run=False):
    session = build_session()

    print("[INFO] loading BUs...")
    bu_map = fetch_business_units(session)

    print("[INFO] loading apps...")
    apps = fetch_all_apps(session)
    print(f"[INFO] found {len(apps)} apps")

    csv_rows = []

    # iterate each app and determine required BU action
    for app in apps:
        profile = app.get("profile") or {}
        app_name = profile.get("name") or "<no-name>"
        app_guid = app.get("guid")

        # base CSV row
        row = {
            "app_name": app_name,
            "app_guid": app_guid or "",
            "bu_name": "",
            "current_bu_guid": "",
            "target_bu_guid": "",
            "bu_action": "",
            "app_action": "",
        }

        if not app_guid:
            print(f"[SKIP] '{app_name}' (no GUID)")
            if dry_run:
                row["app_action"] = "skip_no_guid"
                csv_rows.append(row)
            continue

        # extract BU prefix from naming convention
        bu_name = extract_bu_name(app_name)
        row["bu_name"] = bu_name or ""

        if not bu_name:
            print(f"[SKIP] '{app_name}' (unsupported name)")
            if dry_run:
                row["app_action"] = "skip_name_format"
                csv_rows.append(row)
            continue

        # resolve (or create) BU GUID
        if bu_name in bu_map:
            bu_guid = bu_map[bu_name]
            bu_action = "existing"
        else:
            bu_guid = create_business_unit(session, bu_name, dry_run=dry_run)
            bu_map[bu_name] = bu_guid
            bu_action = "create_dryrun" if dry_run else "create"

        # fetch current BU assignment
        full = get_app_details(session, app_guid)
        current_guid = full.get("profile", {}).get("business_unit", {}).get("guid")

        row["current_bu_guid"] = current_guid or ""
        row["target_bu_guid"] = bu_guid or ""

        # fetch current BU assignment
        if current_guid == bu_guid:
            print(f"[SKIP] '{app_name}' already in '{bu_name}'")
            app_action = "already_in_bu"
        else:
            # perform or simulate assignment
            update_app_business_unit(
                session, app_name, app_guid, full, bu_name, bu_guid, dry_run=dry_run
            )
            app_action = "assign_dryrun" if dry_run else "assign"

        if dry_run:
            row["bu_action"] = bu_action
            row["app_action"] = app_action
            csv_rows.append(row)

    # write full dry-run report after processing
    if dry_run:
        write_dry_run_csv(csv_rows)


def main():
    parser = argparse.ArgumentParser(
        description="Assign apps to BUs by first 4 letters (AAAA-) naming convention."
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        process_apps(dry_run=args.dry_run)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
