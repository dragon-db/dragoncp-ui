#!/usr/bin/env python3
"""Quick script to verify v2 migration schema"""
import sqlite3
import os

db_path = "docs/database/test_migration_v2.db"
if not os.path.exists(db_path):
    print(f"Database not found: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# List all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cursor.fetchall()]
print("=== Tables in v2 database ===")
for t in tables:
    print(f"  - {t}")

print("\n=== Verifying v2 schema ===")
# Check for expected v2 tables
expected_tables = ['transfers', 'radarr_webhook', 'sonarr_webhook', 'rename_webhook', 'app_settings', 'backup', 'backup_file']
for t in expected_tables:
    if t in tables:
        print(f"  ✓ {t} exists")
    else:
        print(f"  ✗ {t} MISSING!")

# Check for removed v1 tables
old_tables = ['webhook_notifications', 'series_webhook_notifications', 'rename_notifications', 'transfer_backups', 'transfer_backup_files']
print("\n=== Checking old v1 tables removed ===")
for t in old_tables:
    if t in tables:
        print(f"  ✗ {t} still exists!")
    else:
        print(f"  ✓ {t} removed")

# Check column renames in transfers table
cursor.execute("PRAGMA table_info(transfers)")
transfer_columns = [col[1] for col in cursor.fetchall()]
print("\n=== Transfers table columns ===")
print(f"  Columns: {', '.join(transfer_columns)}")

# Check for v2 column changes
print("\n=== Verifying v2 column renames ===")
if 'operation_type' in transfer_columns:
    print("  ✓ transfer_type renamed to operation_type")
else:
    print("  ✗ operation_type column missing!")

if 'rsync_process_id' in transfer_columns:
    print("  ✓ process_id renamed to rsync_process_id")
else:
    print("  ✗ rsync_process_id column missing!")

if 'episode_name' not in transfer_columns:
    print("  ✓ episode_name column removed")
else:
    print("  ✗ episode_name still exists!")

if 'parsed_episode' not in transfer_columns:
    print("  ✓ parsed_episode column removed")
else:
    print("  ✗ parsed_episode still exists!")

# Check radarr_webhook columns
cursor.execute("PRAGMA table_info(radarr_webhook)")
webhook_columns = [col[1] for col in cursor.fetchall()]
print("\n=== Radarr webhook columns ===")
if 'completed_at' in webhook_columns:
    print("  ✓ synced_at renamed to completed_at")
else:
    print("  ✗ completed_at column missing!")

if 'updated_at' in webhook_columns:
    print("  ✓ updated_at column added")
else:
    print("  ✗ updated_at column missing!")

# Check backup table columns
cursor.execute("PRAGMA table_info(backup)")
backup_columns = [col[1] for col in cursor.fetchall()]
print("\n=== Backup table columns ===")
if 'backup_path' in backup_columns:
    print("  ✓ backup_dir renamed to backup_path")
else:
    print("  ✗ backup_path column missing!")

if 'episode_name' not in backup_columns:
    print("  ✓ episode_name column removed from backup")
else:
    print("  ✗ episode_name still exists in backup!")

print("\n✅ Schema verification complete!")
conn.close()
