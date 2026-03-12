# PathService Implementation Summary

## Overview
Implemented a centralized `PathService` and improved path handling to ensure consistent destination path construction across all transfer operations. This fix eliminates the issue where dry-run and actual sync used different folder names, and ensures the application uses actual folder paths from the remote server instead of reconstructing them from title fields.

---

## 🎯 Original Problem

### **Issue Discovered:**
The application was using **different folder names** for dry-run validation vs actual sync operations.

### **Root Cause:**
```
Webhook JSON:     "title": "New Gods: Nezha Reborn"        (unsanitized, has colon)
Remote Folder:    "New Gods Nezha Reborn (2021)"           (sanitized by Radarr, no colon)

❌ Actual Sync:   Used title field → /local/movies/New Gods: Nezha Reborn (2021)
✅ Dry-Run:       Used folder_path → /local/movies/New Gods Nezha Reborn (2021)

Result: Paths don't match! Dry-run validates different path than sync uses.
```

**The application was using two different strategies:**
1. **Actual Sync**: Used `title` field from webhook JSON (contained unsanitized characters like `:`)
2. **Dry-Run**: Extracted folder name from actual file system path (already sanitized by Radarr/Sonarr)

This caused mismatches like:
- Actual sync destination: `/media/movies/New Gods: Nezha Reborn (2021)` (with colon)
- Dry-run destination: `/media/movies/New Gods Nezha Reborn (2021)` (without colon)

---

## 🔧 Solution Implemented (Two-Part Fix)

### **Part 1: Centralized PathService**
Created a single service to handle ALL destination path construction

### **Part 2: Use Actual Paths from Webhook**
Use real folder paths from webhook instead of reconstructing from title/season_number

---

## 📦 Part 1: PathService Implementation

### **1. Created New Service** (`services/path_service.py`)

**Purpose:** Centralized service for consistent path transformation (remote → local)

**Key Methods:**
```python
class PathService:
    def get_destination_path(source_path, media_type) → str
        # Main method: Transform remote path to local path
    
    def extract_relative_structure(source_path, media_type) → str
        # Extract folder structure to preserve
    
    def get_base_destination(media_type) → str
        # Get configured local base path
    
    def extract_folder_components(source_path, media_type) → Tuple
        # Extract (folder_name, season_name) from path
    
    def construct_destination_from_components(...) → str
        # Build path from components (for manual transfers)
    
    def get_source_path_from_notification(...) → str
        # Extract source path from webhook notification
```

**Core Principle:**
> **Extract folder structure from actual file system paths, not from title fields**

This ensures:
- Folder names are already sanitized by Radarr/Sonarr
- No special character issues (`:`, `?`, `*`, etc.)
- Dry-run and actual sync use identical paths

**Example Transformation:**
```python
# Input
source = "/remote/Movies/New Gods Nezha Reborn (2021)"
media = "movies"

# Output (base path replaced, structure preserved)
dest = "/local/movies/New Gods Nezha Reborn (2021)"
```

### **2. Updated All Callers to Use PathService**

#### **services/webhook_service.py** (Movie Sync)
**Before:**
```python
folder_name = notification['title']  # Uses unsanitized title
if notification.get('year'):
    folder_name = f"{notification['title']} ({notification['year']})"
dest_path = f"{dest_base}/{folder_name}"
```

**After:**
```python
source_path = notification['folder_path']  # Actual remote path
dest_path = self.path_service.get_destination_path(source_path, 'movies')
folder_name = os.path.basename(source_path.rstrip('/'))  # Extract from path
```

#### **services/webhook_service.py** (Series/Anime Sync)
**Before:**
```python
series_title = notification['series_title']  # Uses unsanitized title
folder_name = f"{series_title} ({notification['year']})"
season_name = f"Season {season_number:02d}"
dest_path = f"{dest_base}/{folder_name}/{season_name}"
```

**After:**
```python
# Uses season_path with fallback (see Part 2 for details)
source_path = notification.get('season_path') or f"{series_path}/Season {season_number:02d}"
dest_path = self.path_service.get_destination_path(source_path, media_type)
folder_name, season_name = self.path_service.extract_folder_components(source_path, media_type)
```

#### **services/transfer_coordinator.py** (Dry-Run Validation)
**Before:**
```python
series_title = notification['series_title']  # Uses unsanitized title
folder_name = f"{series_title} ({notification['year']})"
season_name = f"Season {season_number:02d}"
dest_path = f"{dest_base}/{folder_name}/{season_name}"
```

**After:**
```python
# Uses season_path with fallback (see Part 2 for details)
source_path = notification.get('season_path') or f"{series_path}/Season {season_number:02d}"
dest_path = self.path_service.get_destination_path(source_path, media_type)
```

#### **routes/webhooks.py** (Dry-Run Endpoints)
**Before:**
```python
folder_name = os.path.basename(source_path.rstrip('/'))  # Was already correct!
dest_path = os.path.join(movie_dest_base, folder_name)
```

**After:**
```python
dest_path = transfer_coordinator.path_service.get_destination_path(source_path, media_type)
```

---

## 📦 Part 2: Season Path Improvement

### **Problem Identified:**
Even with PathService, we were still **reconstructing** the season path instead of using the actual path from the webhook.

```python
# We were doing this:
source_path = f"{series_path}/Season {season_number:02d}"  # Reconstructed!

# But webhook ALREADY provides:
season_path = notification['season_path']  # Actual path from episode file!
```

**Issues with Reconstruction:**
1. ❌ **Assumes format**: Hardcodes "Season XX" format assumption
2. ❌ **Not using real data**: Webhook ALREADY provides the actual path
3. ❌ **Brittle**: Breaks if Sonarr changes naming convention
4. ❌ **Inconsistent with movies**: Movies use `folder_path` (actual path), series reconstructed

### **Solution: Use Actual season_path**

**Priority Logic:**
```python
if season_path:
    # PRIMARY: Use actual path from webhook (best)
    source_path = season_path
    print(f"📁 Using actual season_path from webhook: {source_path}")
elif series_path and season_number:
    # FALLBACK: Reconstruct only if needed
    source_path = f"{series_path.rstrip('/')}/Season {season_number:02d}"
    print(f"⚠️  season_path not in notification, reconstructed: {source_path}")
elif series_path:
    # EDGE CASE: Whole series sync
    source_path = series_path
    print(f"📁 Using series_path for whole series sync: {source_path}")
else:
    # ERROR: No path info
    return error
```

**Where season_path Comes From:**
```python
# In webhook parsing (webhook_service.py):
episode_file_path = "/remote/TVShows/Breaking Bad/Season 01/episode.mkv"
season_path = os.path.dirname(episode_file_path)
# Result: "/remote/TVShows/Breaking Bad/Season 01"
```

This is the **ACTUAL folder** created by Sonarr on disk!

**Benefits:**
1. ✅ **Uses real data**: `season_path` is extracted from actual episode file path
2. ✅ **No assumptions**: Works with any folder naming convention
3. ✅ **Future-proof**: Works even if Sonarr changes format
4. ✅ **Consistent**: Same approach as movies (use actual paths from webhook)

---

## 📊 Files Modified

### **Files Created:**
1. ✅ `services/path_service.py` (274 lines) - New centralized path service

### **Files Modified:**
1. ✅ `services/webhook_service.py` 
   - Added PathService import and initialization
   - Updated `trigger_webhook_sync()` - use folder_path
   - Updated `trigger_series_webhook_sync()` - use season_path with fallback

2. ✅ `services/transfer_coordinator.py`
   - Added PathService import and initialization
   - Updated `perform_dry_run_validation()` - use season_path with fallback

3. ✅ `routes/webhooks.py`
   - Updated `api_webhook_dry_run()` - use PathService
   - Updated `api_series_webhook_dry_run()` - use PathService + season_path with fallback

---

## ✅ Problems Solved

### **1. Special Characters in Titles**
**Before:** 
- Movie: "New Gods: Nezha Reborn" → Creates folder with `:` → Fails
- Series: "CSI: Crime Scene Investigation" → Creates folder with `:` → Fails

**After:**
- Uses actual folder names from remote server (already sanitized)
- Works with any special characters (`:`, `?`, `*`, etc.)

### **2. Dry-Run vs Actual Sync Mismatch**
**Before:**
- Dry-run: `/local/movies/New Gods Nezha Reborn (2021)` (from folder_path)
- Actual sync: `/local/movies/New Gods: Nezha Reborn (2021)` (from title)
- Result: Validates wrong path!

**After:**
- Both use identical path from PathService
- Both extract from actual remote paths
- Result: Validates the exact path that will be synced ✅

### **3. Hardcoded Format Assumptions**
**Before:**
- Assumed Sonarr uses "Season XX" format
- Would break with custom naming
- Not future-proof

**After:**
- Uses actual season_path from webhook
- Works with any naming convention
- Future-proof against Sonarr changes

### **4. Inconsistent Path Logic**
**Before:**
- Movies: Extract from folder_path ✅
- Series: Reconstruct from title + season_number ❌
- Dry-run: Extract from path ✅
- Actual sync: Use title field ❌

**After:**
- Movies: Use folder_path via PathService ✅
- Series: Use season_path via PathService ✅
- Dry-run: Use PathService ✅
- Actual sync: Use PathService ✅

---

## 🎯 Key Principles Established

### **1. Use Real Data from Source**
```
✅ DO: Extract folder names from actual remote paths
❌ DON'T: Reconstruct folder names from title fields
```

### **2. Single Source of Truth**
```
✅ DO: Use PathService for all path transformations
❌ DON'T: Duplicate path logic in multiple places
```

### **3. Primary with Fallback**
```
✅ DO: Use actual paths (season_path), fallback to reconstruction
❌ DON'T: Always reconstruct even when real data available
```

### **4. Transform, Don't Construct**
```
✅ DO: PathService transforms existing paths (remote → local)
❌ DON'T: PathService constructs paths from components
```

**Separation of Concerns:**
- **Webhook**: Provides actual paths from remote server ✅
- **Caller**: Selects which path to use (season_path vs fallback) ✅
- **PathService**: Transforms remote paths to local paths ✅

---

## 🧪 Testing Guide

### **Test Scenarios:**

#### **1. Movie with Special Characters**
```
Title: "New Gods: Nezha Reborn"
Remote: /remote/Movies/New Gods Nezha Reborn (2021)
Expected Local: /local/movies/New Gods Nezha Reborn (2021)

✅ Test: Dry-run shows safe to sync
✅ Test: Actual sync creates correct folder
✅ Test: Both use same path
```

#### **2. Series with Special Characters**
```
Title: "CSI: Crime Scene Investigation"
Remote: /remote/TVShows/CSI Crime Scene Investigation/Season 01
Expected Local: /local/tvshows/CSI Crime Scene Investigation/Season 01

✅ Test: Dry-run shows safe to sync
✅ Test: Actual sync creates correct folder
✅ Test: Logs show "Using actual season_path"
```

#### **3. Anime Episode**
```
Title: "Attack on Titan"
Remote: /remote/Anime/Attack on Titan (2013)/Season 01
Expected Local: /local/anime/Attack on Titan (2013)/Season 01

✅ Test: Uses anime destination base path
✅ Test: season_path extracted correctly
✅ Test: Logs show "Using actual season_path"
```

#### **4. Fallback Test (Missing season_path)**
```
Simulate: Webhook missing season_path field
Expected: Logs show "⚠️  season_path not in notification, reconstructed"
Expected: Falls back to series_path + Season {num:02d}

✅ Test: Fallback creates correct path
✅ Test: Warning logged appropriately
```

#### **5. End-to-End Consistency**
```
For same notification:
1. Perform dry-run
2. Note destination path in logs
3. Start actual sync
4. Note destination path in logs
Expected: Both paths are IDENTICAL

✅ Test: Paths match exactly
```

#### **6. Non-Standard Season Folders**
```
If Sonarr uses custom naming (e.g., "S01" instead of "Season 01")
Expected: season_path captures the actual folder name
Expected: This would FAIL with old reconstruction method

✅ Test: Works with any naming convention
```

---

## 📈 Benefits Summary

| Benefit | Impact |
|---------|--------|
| **Consistency** | Dry-run and actual sync use identical paths |
| **Correctness** | Folder names match remote server exactly |
| **Robustness** | Works with special characters in titles |
| **Maintainability** | Single source of truth for path logic |
| **Future-Proof** | Uses real paths, no format assumptions |
| **Debuggability** | Clear logging shows which paths used |

---

## 📝 Logging Output

The implementation includes helpful logging to show which path method is being used:

### **When using actual season_path (normal case):**
```
📁 Using actual season_path from webhook: /remote/TVShows/Breaking Bad/Season 01
```

### **When falling back to reconstruction:**
```
⚠️  season_path not in notification, reconstructed: /remote/TVShows/Breaking Bad/Season 01
```

This makes it easy to:
- Verify the code is working correctly
- Debug if season_path is missing
- Monitor if we're relying on fallback too often

---

## 📋 Example Path Transformations

### **Movies:**
```
Remote:  /home/dragondb/media/Movies/New Gods Nezha Reborn (2021)
Local:   /home/dragondb/media_external/media/movies/New Gods Nezha Reborn (2021)
         ↑ Base path replaced, folder name preserved exactly ↑
```

### **Series:**
```
Remote:  /home/dragondb/media/TVShows/Breaking Bad (2008)/Season 01
Local:   /home/dragondb/media_external/media/tvshows/Breaking Bad (2008)/Season 01
         ↑ Base path replaced, series/season structure preserved exactly ↑
```

### **Anime:**
```
Remote:  /home/dragondb/media/Anime/Attack on Titan (2013)/Season 01
Local:   /home/dragondb/media_external/media/anime/Attack on Titan (2013)/Season 01
         ↑ Base path replaced, structure preserved exactly ↑
```

---

## 🚀 Deployment Notes

### **No Migration Required:**
- ✅ No database schema changes
- ✅ No configuration changes needed
- ✅ No breaking changes for existing transfers
- ✅ Works with existing `.env` settings

### **Backward Compatibility:**
- ✅ Existing transfers will complete normally
- ✅ Only new transfers use the new path logic
- ✅ Manual transfers still work (unchanged)

### **Deployment Steps:**
1. Deploy code changes
2. Restart application
3. Test with new webhook (verify logs)
4. Monitor for any fallback warnings

### **Rollback Plan:**
- Changes are isolated to path construction
- Can revert if issues found
- No database cleanup needed

---

## 📝 Code Quality

### **Linter Status:**
✅ All files pass linting (no errors introduced)

### **Documentation:**
✅ Extensive inline comments explaining logic
✅ Clear docstrings for all methods
✅ Comprehensive markdown documentation

### **Code Structure:**
✅ Clean separation of concerns
✅ Single responsibility principle followed
✅ DRY principle applied (no duplication)

---

## 🎓 Lessons Learned

### **1. Trust the Source Data**
When the source system (Radarr/Sonarr) provides actual paths, use them instead of reconstructing.

### **2. Centralize Path Logic**
Having path construction in multiple places leads to inconsistencies. Single service is better.

### **3. Primary with Fallback Pattern**
```python
if real_data_available:
    use_real_data()
else:
    use_fallback()
```
This provides robustness while preferring accuracy.

### **4. Make Assumptions Visible**
When we must make assumptions (fallback), log them clearly for debugging.

---

## 🔮 Future Improvements (Optional)

### **Possible Enhancements:**

1. **Add Unit Tests for PathService**
   - Test with various path formats
   - Test with special characters
   - Test edge cases

2. **Monitor Fallback Usage**
   - Add metrics for when fallback is used
   - Alert if fallback used too frequently
   - Investigate why season_path missing

3. **Validate Against Remote**
   - Before sync, verify remote path exists
   - Warn if reconstructed path differs from actual
   - Prevent sync to wrong location

4. **Path Normalization**
   - Handle different path separators (Windows vs Linux)
   - Remove redundant slashes
   - Normalize Unicode characters

---

## ✨ Final Result

The DragonCP application now:

1. ✅ Uses **actual folder paths** from remote server
2. ✅ Has **consistent path logic** everywhere (PathService)
3. ✅ Handles **special characters** correctly
4. ✅ Validates **exact paths** that will be synced
5. ✅ Provides **fallback** for edge cases
6. ✅ Has **clear logging** for debugging
7. ✅ Is **future-proof** against naming changes

**The original issue is completely resolved:**
```
Before: "New Gods: Nezha Reborn" → Mismatch between dry-run and sync
After:  "New Gods Nezha Reborn" → Consistent paths everywhere ✅
```

**Consistency Achieved:**
| Media Type | Path Field Used | Source |
|------------|----------------|--------|
| **Movies** | `folder_path` | ✅ Actual remote folder path |
| **Series/Anime** | `season_path` (with fallback) | ✅ Actual remote folder path |

The fix is comprehensive, covering all code paths: webhook syncs (movies, series, anime), dry-runs (webhook and manual), and validation logic.
