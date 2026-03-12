# DragonCP Documentation

This directory contains all feature-specific documentation for the DragonCP project, organized by feature area.

## 📁 Documentation Structure

### `/auto-sync/`
Auto-sync functionality for series and anime transfers
- **SERIES_ANIME_AUTO_SYNC_IMPLEMENTATION.md** - Complete auto-sync implementation guide covering webhook reception, batching, dry-run validation, and Discord notifications
- **v3_autosync_implementation.md** - V3 redesign with intelligent queue management, explicit state tracking, and dynamic queue type conversion

### `/notifications/`
Discord notification system
- **DISCORD_NOTIFICATION_IMPLEMENTATION.md** - Discord webhook notification functionality for completed transfers

### `/path-service/`
Centralized path handling service
- **PATHSERVICE_IMPLEMENTATION_SUMMARY.md** - PathService implementation ensuring consistent destination path construction across all transfer operations

### `/queue-management/`
Transfer queue management system
- **QUEUE_MANAGEMENT_IMPLEMENTATION.md** - Advanced queue management with duplicate detection, max 3 concurrent transfers, and automatic promotion

- **SYNC_APPLICATION_ANALYSIS.md** - End-to-end backend sync architecture analysis with performance and QoS improvement recommendations

### `/refactoring/`
Code refactoring documentation
- **REFACTORING_GUIDE.md** - Complete refactoring guide showing the transformation from monolithic files to modular architecture (Models/Services/Routes)

### `/database/`
Database schema and migration documentation
- **V2_REDESIGN_PLAN.md** - Database v2 redesign plan
- **v2_schema.md** - Database v2 schema documentation

## 🔍 Quick Reference

### Finding Documentation by Topic

| Topic | Location |
|-------|----------|
| **Auto-sync for series/anime** | `/auto-sync/` |
| **Discord notifications** | `/notifications/` |
| **Path handling & destination paths** | `/path-service/` |
| **Queue system & concurrent transfers** | `/queue-management/` |
| **Code architecture & refactoring** | `/refactoring/` |
| **Database schema & migrations** | `/database/` |

## 📝 Documentation Standards

All documentation files follow these conventions:
- **Markdown format** (.md extension)
- **Clear headings** with table of contents for longer docs
- **Code examples** with syntax highlighting
- **Flow diagrams** using ASCII art or mermaid
- **Implementation details** including file paths and function names
- **Testing scenarios** and edge cases

## 🚀 Getting Started

1. **New to DragonCP?** Start with `/refactoring/REFACTORING_GUIDE.md` to understand the architecture
2. **Setting up auto-sync?** Check `/auto-sync/` for complete implementation guides
3. **Working with transfers?** Review `/queue-management/` and `/path-service/`
4. **Database changes?** See `/database/` for schema documentation

## 📅 Last Updated

Documentation structure reorganized: December 31, 2025


