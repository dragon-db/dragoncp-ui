#!/usr/bin/env python3
"""
DragonCP Database Migration Script: v1 to v2

This script migrates the database from v1 schema to v2 schema.
The migration will:
1. Optionally backup the old database
2. Extract data to migrate (app_settings, backups)
3. Drop all old tables
4. Create new v2 schema
5. Migrate extracted data
6. Validate the new database

Usage:
    python scripts/migrate_v1_to_v2.py [--backup] [--migrate-data] [--db-path PATH]

Options:
    --backup        Create a backup of the old database before migration
    --migrate-data  Migrate critical data (settings, backups)
    --db-path PATH  Custom database path (default: dragoncp.db in project root)
"""

import sqlite3
import os
import sys
import shutil
import argparse
from datetime import datetime
from pathlib import Path


def get_db_path():
    """Get the database path"""
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(script_dir, "dragoncp.db")


def backup_database(db_path):
    """Create a backup of the database"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.v1_backup_{timestamp}"
    print(f"📦 Creating backup: {backup_path}")
    shutil.copy2(db_path, backup_path)
    print(f"✅ Backup created: {backup_path}")
    return backup_path


def extract_app_settings(conn):
    """Extract app_settings data from v1"""
    try:
        cursor = conn.execute('SELECT key, value, updated_at FROM app_settings')
        settings = cursor.fetchall()
        print(f"   ✓ Found {len(settings)} app settings")
        return settings
    except Exception as e:
        print(f"   ⚠️  Error extracting app_settings: {e}")
        return []


def extract_backups(conn):
    """Extract backup data from v1 (transfer_backups)"""
    try:
        cursor = conn.execute('''
            SELECT backup_id, transfer_id, media_type, folder_name, season_name,
                   source_path, dest_path, backup_dir, file_count, total_size,
                   status, created_at, restored_at
            FROM transfer_backups
        ''')
        backups = cursor.fetchall()
        print(f"   ✓ Found {len(backups)} backup records")
        return backups
    except Exception as e:
        print(f"   ⚠️  Error extracting backups: {e}")
        return []


def extract_backup_files(conn):
    """Extract backup file data from v1 (transfer_backup_files)"""
    try:
        cursor = conn.execute('''
            SELECT backup_id, relative_path, original_path, file_size, modified_time,
                   context_media_type, context_title, context_release_year, context_series_title,
                   context_season, context_episode, context_absolute, context_key, context_display,
                   created_at
            FROM transfer_backup_files
        ''')
        files = cursor.fetchall()
        print(f"   ✓ Found {len(files)} backup files")
        return files
    except Exception as e:
        print(f"   ⚠️  Error extracting backup files: {e}")
        return []


def drop_v1_tables(conn):
    """Drop all v1 tables"""
    print("🗑️  Dropping v1 tables...")
    
    v1_tables = [
        'transfers',
        'webhook_notifications',
        'series_webhook_notifications',
        'rename_notifications',
        'app_settings',
        'transfer_backups',
        'transfer_backup_files'
    ]
    
    for table in v1_tables:
        try:
            conn.execute(f'DROP TABLE IF EXISTS {table}')
            print(f"   ✓ Dropped {table}")
        except Exception as e:
            print(f"   ⚠️  Error dropping {table}: {e}")
    
    conn.commit()
    print("✅ v1 tables dropped")


def create_v2_schema(conn):
    """Create v2 database schema"""
    print("🔨 Creating v2 database schema...")
    
    # ==========================================
    # Table: transfers
    # ==========================================
    # Changes from v1:
    # - REMOVED: episode_name, parsed_episode
    # - RENAMED: transfer_type → operation_type
    # - RENAMED: process_id → rsync_process_id
    conn.execute('''
        CREATE TABLE IF NOT EXISTS transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transfer_id TEXT UNIQUE NOT NULL,
            media_type TEXT NOT NULL,
            folder_name TEXT NOT NULL,
            season_name TEXT,
            source_path TEXT NOT NULL,
            dest_path TEXT NOT NULL,
            operation_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            progress TEXT DEFAULT '',
            rsync_process_id INTEGER,
            logs TEXT DEFAULT '[]',
            parsed_title TEXT,
            parsed_season TEXT,
            start_time DATETIME,
            end_time DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("   ✓ Created transfers table")
    
    # ==========================================
    # Table: radarr_webhook (renamed from webhook_notifications)
    # ==========================================
    # Changes from v1:
    # - RENAMED: table webhook_notifications → radarr_webhook
    # - RENAMED: synced_at → completed_at
    # - ADDED: updated_at
    conn.execute('''
        CREATE TABLE IF NOT EXISTS radarr_webhook (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notification_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            year INTEGER,
            folder_path TEXT NOT NULL,
            poster_url TEXT,
            requested_by TEXT,
            file_path TEXT NOT NULL,
            quality TEXT,
            size INTEGER DEFAULT 0,
            languages TEXT DEFAULT '[]',
            subtitles TEXT DEFAULT '[]',
            release_title TEXT,
            release_indexer TEXT,
            release_size INTEGER DEFAULT 0,
            tmdb_id INTEGER,
            imdb_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            error_message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            transfer_id TEXT,
            raw_webhook_data TEXT
        )
    ''')
    print("   ✓ Created radarr_webhook table")
    
    # ==========================================
    # Table: sonarr_webhook (renamed from series_webhook_notifications)
    # ==========================================
    # Changes from v1:
    # - RENAMED: table series_webhook_notifications → sonarr_webhook
    # - RENAMED: synced_at → completed_at
    # - ADDED: updated_at
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sonarr_webhook (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notification_id TEXT UNIQUE NOT NULL,
            media_type TEXT NOT NULL,
            series_title TEXT NOT NULL,
            series_title_slug TEXT,
            series_id INTEGER,
            series_path TEXT NOT NULL,
            year INTEGER,
            tvdb_id INTEGER,
            tv_maze_id INTEGER,
            tmdb_id INTEGER,
            imdb_id TEXT,
            poster_url TEXT,
            banner_url TEXT,
            tags TEXT DEFAULT '[]',
            original_language TEXT,
            requested_by TEXT,
            season_number INTEGER,
            episode_count INTEGER DEFAULT 1,
            episodes TEXT DEFAULT '[]',
            episode_files TEXT DEFAULT '[]',
            season_path TEXT NOT NULL,
            release_title TEXT,
            release_indexer TEXT,
            release_size INTEGER DEFAULT 0,
            download_client TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            error_message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            transfer_id TEXT,
            requires_manual_sync INTEGER DEFAULT 0,
            manual_sync_reason TEXT,
            auto_sync_scheduled_at DATETIME,
            dry_run_result TEXT,
            dry_run_performed_at DATETIME,
            raw_webhook_data TEXT
        )
    ''')
    print("   ✓ Created sonarr_webhook table")
    
    # ==========================================
    # Table: rename_webhook (renamed from rename_notifications)
    # ==========================================
    # Changes from v1:
    # - RENAMED: table rename_notifications → rename_webhook
    # - RENAMED: processed_at → completed_at
    # - ADDED: updated_at
    conn.execute('''
        CREATE TABLE IF NOT EXISTS rename_webhook (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notification_id TEXT UNIQUE NOT NULL,
            media_type TEXT NOT NULL,
            series_title TEXT NOT NULL,
            series_id INTEGER,
            series_path TEXT NOT NULL,
            renamed_files TEXT DEFAULT '[]',
            total_files INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            error_message TEXT,
            raw_webhook_data TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("   ✓ Created rename_webhook table")
    
    # ==========================================
    # Table: app_settings (unchanged)
    # ==========================================
    conn.execute('''
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("   ✓ Created app_settings table")
    
    # ==========================================
    # Table: backup (renamed from transfer_backups)
    # ==========================================
    # Changes from v1:
    # - RENAMED: table transfer_backups → backup
    # - REMOVED: episode_name
    # - RENAMED: backup_dir → backup_path
    # - ADDED: updated_at
    conn.execute('''
        CREATE TABLE IF NOT EXISTS backup (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            backup_id TEXT UNIQUE NOT NULL,
            transfer_id TEXT NOT NULL,
            media_type TEXT,
            folder_name TEXT,
            season_name TEXT,
            source_path TEXT NOT NULL,
            dest_path TEXT NOT NULL,
            backup_path TEXT NOT NULL,
            file_count INTEGER DEFAULT 0,
            total_size INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ready',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            restored_at DATETIME,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("   ✓ Created backup table")
    
    # ==========================================
    # Table: backup_file (renamed from transfer_backup_files)
    # ==========================================
    # Changes from v1:
    # - RENAMED: table transfer_backup_files → backup_file
    conn.execute('''
        CREATE TABLE IF NOT EXISTS backup_file (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            backup_id TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            original_path TEXT NOT NULL,
            file_size INTEGER,
            modified_time INTEGER,
            context_media_type TEXT,
            context_title TEXT,
            context_release_year TEXT,
            context_series_title TEXT,
            context_season TEXT,
            context_episode TEXT,
            context_absolute TEXT,
            context_key TEXT,
            context_display TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("   ✓ Created backup_file table")
    
    conn.commit()
    
    # Create indexes
    print("📊 Creating indexes...")
    
    # Transfer indexes
    conn.execute('CREATE INDEX IF NOT EXISTS idx_transfer_id ON transfers(transfer_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_status ON transfers(status)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON transfers(created_at)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_dest_status ON transfers(dest_path, status)')
    
    # Radarr webhook indexes
    conn.execute('CREATE INDEX IF NOT EXISTS idx_radarr_webhook_notification_id ON radarr_webhook(notification_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_radarr_webhook_status ON radarr_webhook(status)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_radarr_webhook_created_at ON radarr_webhook(created_at)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_radarr_webhook_transfer_id ON radarr_webhook(transfer_id)')
    
    # Sonarr webhook indexes
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sonarr_webhook_notification_id ON sonarr_webhook(notification_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sonarr_webhook_status ON sonarr_webhook(status)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sonarr_webhook_transfer_id ON sonarr_webhook(transfer_id)')
    
    # Rename webhook indexes
    conn.execute('CREATE INDEX IF NOT EXISTS idx_rename_webhook_notification_id ON rename_webhook(notification_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_rename_webhook_status ON rename_webhook(status)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_rename_webhook_created_at ON rename_webhook(created_at)')
    
    # Backup indexes
    conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_transfer_id ON backup(transfer_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_file_backup_id ON backup_file(backup_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_file_context_key ON backup_file(context_key)')
    
    conn.commit()
    print("✅ v2 schema created successfully")


def migrate_app_settings(conn, settings):
    """Migrate app_settings data to v2"""
    if not settings:
        print("   ℹ️  No app settings to migrate")
        return 0
    
    conn.executemany('''
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, ?)
    ''', settings)
    conn.commit()
    print(f"   ✓ Migrated {len(settings)} app settings")
    return len(settings)


def migrate_backups(conn, backups):
    """Migrate backup data to v2 (backup_dir → backup_path, remove episode_name)"""
    if not backups:
        print("   ℹ️  No backups to migrate")
        return 0
    
    # Map old columns to new structure (skipping episode_name, renaming backup_dir → backup_path)
    for backup in backups:
        # backup[7] is backup_dir which becomes backup_path
        conn.execute('''
            INSERT INTO backup (
                backup_id, transfer_id, media_type, folder_name, season_name,
                source_path, dest_path, backup_path, file_count, total_size,
                status, created_at, restored_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (
            backup[0],  # backup_id
            backup[1],  # transfer_id
            backup[2],  # media_type
            backup[3],  # folder_name
            backup[4],  # season_name
            backup[5],  # source_path
            backup[6],  # dest_path
            backup[7],  # backup_dir → backup_path
            backup[8],  # file_count
            backup[9],  # total_size
            backup[10], # status
            backup[11], # created_at
            backup[12], # restored_at
        ))
    
    conn.commit()
    print(f"   ✓ Migrated {len(backups)} backup records")
    return len(backups)


def migrate_backup_files(conn, files):
    """Migrate backup file data to v2"""
    if not files:
        print("   ℹ️  No backup files to migrate")
        return 0
    
    conn.executemany('''
        INSERT INTO backup_file (
            backup_id, relative_path, original_path, file_size, modified_time,
            context_media_type, context_title, context_release_year, context_series_title,
            context_season, context_episode, context_absolute, context_key, context_display,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', files)
    conn.commit()
    print(f"   ✓ Migrated {len(files)} backup files")
    return len(files)


def validate_v2_schema(conn):
    """Validate the v2 schema was created correctly"""
    print("🔍 Validating v2 schema...")
    
    expected_tables = [
        'transfers',
        'radarr_webhook',
        'sonarr_webhook',
        'rename_webhook',
        'app_settings',
        'backup',
        'backup_file'
    ]
    
    # Check all tables exist
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    actual_tables = [row[0] for row in cursor.fetchall()]
    
    missing_tables = [t for t in expected_tables if t not in actual_tables]
    if missing_tables:
        print(f"   ❌ Missing tables: {missing_tables}")
        return False
    print("   ✓ All expected tables exist")
    
    # Validate transfers table has correct columns
    cursor = conn.execute("PRAGMA table_info(transfers)")
    transfer_cols = {row[1] for row in cursor.fetchall()}
    
    # Check removed columns are NOT present
    removed_cols = ['episode_name', 'parsed_episode', 'transfer_type', 'process_id']
    present_removed = [c for c in removed_cols if c in transfer_cols]
    if present_removed:
        print(f"   ❌ Old columns still present in transfers: {present_removed}")
        return False
    print("   ✓ Removed columns not present in transfers")
    
    # Check new columns ARE present
    new_cols = ['operation_type', 'rsync_process_id']
    missing_new = [c for c in new_cols if c not in transfer_cols]
    if missing_new:
        print(f"   ❌ New columns missing in transfers: {missing_new}")
        return False
    print("   ✓ New columns present in transfers")
    
    # Validate webhook tables have completed_at (not synced_at)
    for table in ['radarr_webhook', 'sonarr_webhook', 'rename_webhook']:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        cols = {row[1] for row in cursor.fetchall()}
        
        if 'synced_at' in cols or 'processed_at' in cols:
            print(f"   ❌ Old timestamp column found in {table}")
            return False
        if 'completed_at' not in cols:
            print(f"   ❌ completed_at column missing in {table}")
            return False
        if 'updated_at' not in cols:
            print(f"   ❌ updated_at column missing in {table}")
            return False
    print("   ✓ Timestamp columns correct in webhook tables")
    
    # Validate backup table has backup_path (not backup_dir)
    cursor = conn.execute("PRAGMA table_info(backup)")
    backup_cols = {row[1] for row in cursor.fetchall()}
    
    if 'backup_dir' in backup_cols:
        print("   ❌ Old backup_dir column found in backup")
        return False
    if 'backup_path' not in backup_cols:
        print("   ❌ backup_path column missing in backup")
        return False
    if 'episode_name' in backup_cols:
        print("   ❌ episode_name column found in backup (should be removed)")
        return False
    print("   ✓ backup table columns correct")
    
    print("✅ Schema validation passed!")
    return True


def main():
    """Main migration function"""
    parser = argparse.ArgumentParser(description='Migrate DragonCP database from v1 to v2')
    parser.add_argument('--backup', action='store_true', help='Create backup of old database')
    parser.add_argument('--migrate-data', action='store_true', help='Migrate critical data (settings, backups)')
    parser.add_argument('--db-path', type=str, help='Custom database path')
    args = parser.parse_args()
    
    db_path = args.db_path if args.db_path else get_db_path()
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        print("ℹ️  This is a fresh installation. The v2 schema will be created on first run.")
        sys.exit(0)
    
    print("=" * 60)
    print("🔄 DragonCP Database Migration: v1 → v2")
    print("=" * 60)
    print(f"📁 Database: {db_path}")
    print(f"📅 Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Create backup if requested
    if args.backup:
        backup_path = backup_database(db_path)
        print()
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Extract data to migrate
    migrated_settings = []
    migrated_backups = []
    migrated_backup_files = []
    
    if args.migrate_data:
        print("📋 Extracting data to migrate...")
        migrated_settings = extract_app_settings(conn)
        migrated_backups = extract_backups(conn)
        migrated_backup_files = extract_backup_files(conn)
        print()
    
    # Drop v1 tables
    drop_v1_tables(conn)
    print()
    
    # Create v2 schema
    create_v2_schema(conn)
    print()
    
    # Re-insert migrated data
    if args.migrate_data:
        print("📋 Migrating extracted data...")
        migrate_app_settings(conn, migrated_settings)
        migrate_backups(conn, migrated_backups)
        migrate_backup_files(conn, migrated_backup_files)
        print()
    
    # Validate schema
    validation_passed = validate_v2_schema(conn)
    print()
    
    # VACUUM to reclaim disk space from dropped v1 tables
    print("🗜️  Running VACUUM to reclaim disk space...")
    conn.execute('VACUUM')
    print("✅ VACUUM completed - database file size reduced")
    print()
    
    conn.close()
    
    print("=" * 60)
    if validation_passed:
        print("✅ Migration completed successfully!")
    else:
        print("⚠️  Migration completed with validation warnings!")
    print("=" * 60)
    print()
    print("📝 NEXT STEPS:")
    print("   1. Update your code to use the new v2 schema")
    print("   2. Table names changed:")
    print("      - webhook_notifications → radarr_webhook")
    print("      - series_webhook_notifications → sonarr_webhook")
    print("      - rename_notifications → rename_webhook")
    print("      - transfer_backups → backup")
    print("      - transfer_backup_files → backup_file")
    print("   3. Column names changed:")
    print("      - transfer_type → operation_type")
    print("      - process_id → rsync_process_id")
    print("      - backup_dir → backup_path")
    print("      - synced_at → completed_at")
    print("      - processed_at → completed_at")
    print("   4. Columns removed:")
    print("      - episode_name, parsed_episode (from transfers)")
    print("      - episode_name (from backup)")
    print()


if __name__ == '__main__':
    main()
