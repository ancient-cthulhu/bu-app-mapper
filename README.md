# Veracode Business Unit Auto-Assignment

This project provides a Python script that assigns **Veracode applications to Business Units (BUs)** based on a strict application naming convention.

The script scans all applications in a Veracode tenant, derives the target Business Unit from the application name, ensures the BU exists, and assigns the application if needed. A dry-run mode is included for safe validation and auditing.

---

## How It Works

Applications must follow this naming convention:

```
AAAA-application-name
```

Where:
- `AAAA` (first 4 alphabetic characters before `-`) is used as the Business Unit name

If the BU does not exist, the script creates it.  
If the application is already assigned correctly, no change is made.  
Applications that do not match the naming convention are skipped.

---

## Features

- Automatic Business Unit resolution from app names
- Creates missing Business Units when required
- Assigns applications only when a change is needed
- Dry-run mode with CSV output for review
- Built-in pagination, retries, and API timeouts
- Uses Veracode HMAC authentication

---

## Prerequisites

1. **Python 3.8 or later**
2. Install dependencies:

   ```bash
   pip install requests veracode-api-signing
   ```

3. Configure Veracode API credentials:

   **Linux/macOS**

   ```
   ~/.veracode/credentials
   ```

   **Windows**

   ```
   %USERPROFILE%\.veracode\credentials
   ```

   File contents:

   ```
   [default]
   veracode_api_key_id = YOUR_API_ID
   veracode_api_key_secret = YOUR_API_KEY
   ```

---

## Usage

### Dry Run (Recommended)

Simulates all actions without making changes and generates a CSV report.

```bash
python assign_bu.py --dry-run
```

### Apply Changes

Creates missing Business Units and updates application assignments.

```bash
python assign_bu.py
```

---

## Flags

| Flag | Description |
|-----|-------------|
| `--dry-run` | Simulates BU creation and application assignment without modifying Veracode data. Generates a CSV report (`dry_run_bu_assignments.csv`) with all intended actions. |

---

## Dry-Run Output

When using `--dry-run`, the script generates:

```
dry_run_bu_assignments.csv
```

The CSV includes:
- Application name and GUID
- Current and target Business Unit GUIDs
- Whether a BU would be created
- Whether an application would be reassigned or skipped

This file is intended for validation and approval before running in write mode.

---

## Notes

- Applications without GUIDs are skipped
- Applications not matching the naming convention are skipped
- The script is idempotent: no update is performed if the app is already correctly assigned
- Full application profiles are retrieved before updates to avoid partial overwrites
- Designed for enterprise-scale tenants

---

## Disclaimer

This script modifies Veracode application metadata.  
Always run with `--dry-run` first and review the generated CSV before applying changes in production.
