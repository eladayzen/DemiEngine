# Applied Changes Status Buttons

## What Was Added

3 new buttons on every Applied Changes item for QA workflow:

1. **✓ Resolved** - Mark request as working correctly
2. **✗ Not Resolved** - Mark request as not working
3. **📋 Duplicate & Edit** - Create a new request with same data

---

## How It Works

### Resolved / Not Resolved Toggle

**Behavior:**
- Click **✓ Resolved** → Button turns green, "Not Resolved" becomes inactive
- Click **✗ Not Resolved** → Button turns red, "Resolved" becomes inactive
- Click active button again → Clears status (both buttons inactive)

**Visual States:**

**Inactive (default):**
```
[ ✓ Resolved ]  [ ✗ Not Resolved ]  [ 📋 Duplicate & Edit ]
   ↑ gray          ↑ gray                  ↑ blue
```

**Resolved:**
```
[ ✓ Resolved ]  [ ✗ Not Resolved ]  [ 📋 Duplicate & Edit ]
   ↑ GREEN         ↑ gray (disabled)       ↑ blue
```

**Not Resolved:**
```
[ ✓ Resolved ]  [ ✗ Not Resolved ]  [ 📋 Duplicate & Edit ]
   ↑ gray (disabled)  ↑ RED                ↑ blue
```

**Purpose:**
- QA checklist for yourself
- Track which changes worked
- Quick visual feedback on build quality

---

### Duplicate & Edit

**Behavior:**
1. Click **📋 Duplicate & Edit** button
2. Form opens automatically
3. All fields pre-filled:
   - Category selected
   - Level selected (if Level Design)
   - Screenshot loaded (if available)
   - Text note filled in
4. User can edit any field
5. Submit as new pending request

**Use Cases:**
- "This almost worked, let me tweak it"
- "I want the same change for Level 3"
- "Similar request but slightly different"

**Example:**
```
Original request (Applied):
Category: Graphics & UI
Text: "Change background to dark green #1a472a"
Status: ✓ Resolved

Click "Duplicate & Edit"
  ↓
Form opens with:
Category: Graphics & UI (pre-selected)
Text: "Change background to dark green #1a472a" (pre-filled)
  ↓
User edits:
Text: "Change background to dark blue #1a2a47"
  ↓
Submit → New pending request created
```

---

## UI Layout

### Applied Changes Item

```
┌────────────────────────────────────────────────────────────┐
│ 🎨 Graphics & UI (Global)  │  [ ✓ Resolved           ]    │
│                            │  [ ✗ Not Resolved       ]    │
│ Changed background color.  │  [ 📋 Duplicate & Edit  ]    │
│                            │                               │
│ Updated visual config...   │                               │
└────────────────────────────────────────────────────────────┘
   ↑ Main content area         ↑ Status buttons on right
   ↑ Double-click for details  ↑ Click to set status/duplicate
```

---

## Code Implementation

### New Functions

**veSetRequestStatus(item, status):**
```javascript
function veSetRequestStatus(item, status) {
  if (item.status === status) {
    // Clicking same status again clears it
    item.status = null;
  } else {
    item.status = status;
  }
  veRenderApplied();
}
```

**veDuplicateRequest(item):**
```javascript
function veDuplicateRequest(item) {
  // Show form
  veShowForm();

  // Select the category
  if (item.category) {
    veSelectCategory(item.category);
  }

  // If level_design, select the level
  if (item.category === 'level_design' && item.level_number) {
    setTimeout(function() {
      var levelSelect = document.getElementById('ve-level-select');
      if (levelSelect) {
        levelSelect.value = item.level_number;
        veUpdateSelectedLevel();
      }
    }, 100);
  }

  // Pre-fill screenshot if available
  if (item.clean) {
    veScreenshotB64 = item.clean;
    setTimeout(function() {
      veSetupPathACanvases('data:image/png;base64,' + item.clean);
    }, 200);
  }

  // Pre-fill text note
  setTimeout(function() {
    var textNote = document.getElementById('ve-text-note');
    if (textNote && item.reasoning) {
      textNote.value = item.reasoning;
    }
  }, 300);

  // Scroll to form
  setTimeout(function() {
    document.getElementById('ve-form').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, 400);
}
```

### Updated Card Function

**veCreateRequestCard(item, showDeleteBtn, showStatusBtns):**
- Added 3rd parameter: `showStatusBtns`
- Pending requests: `showDeleteBtn=true, showStatusBtns=false`
- Applied requests: `showDeleteBtn=false, showStatusBtns=true`

---

## User Workflow

### QA After Build

**Step 1:** User builds with 3 pending requests

**Step 2:** User previews the build and tests

**Step 3:** User goes to "Applied Changes" and reviews:
```
📦 build_20260221_180000                    3 change(s)

🎯 Level 2  moderate
Added more cards to Level 2.
  [ ✓ Resolved ] ← Click: "Yes, this worked!"

🎨 Graphics & UI
Changed background color to blue.
  [ ✗ Not Resolved ] ← Click: "No, color is wrong"

✨ Animation
Made victory animation bigger.
  [ ✓ Resolved ] ← Click: "Perfect!"
```

**Step 4:** For the failed request, user clicks "Duplicate & Edit"

**Step 5:** Form opens with pre-filled data:
```
Category: 🎨 Graphics & UI
Text: "Changed background color to blue."
```

**Step 6:** User edits:
```
Text: "Changed background color to darker blue #1a3a5a"
```

**Step 7:** Submit → New pending request → Build again

---

## Visual Design

### Button States

**Resolved (Active):**
- Background: Green (#22c55e)
- Border: Green
- Text: White
- Font weight: Bold

**Not Resolved (Active):**
- Background: Red (#f97583)
- Border: Red
- Text: White
- Font weight: Bold

**Inactive:**
- Background: var(--bg)
- Border: var(--border)
- Text: var(--text)
- Font weight: Normal

**Duplicate & Edit (Always):**
- Background: Blue (#6366f1)
- Border: Blue
- Text: White
- Always active

---

## Data Storage

Each applied request now has a `status` field:
- `null` - No status set (default)
- `'resolved'` - Marked as resolved
- `'not_resolved'` - Marked as not resolved

**Storage:**
```javascript
item.status = 'resolved'; // or 'not_resolved' or null
```

**Persistence:**
- Status persists in memory during session
- Cleared when page refreshes
- (Future: Could save to localStorage or backend)

---

## Files Modified

**File:** `static/index.html`

**Functions added:**
- `veSetRequestStatus(item, status)` - Toggle status
- `veDuplicateRequest(item)` - Duplicate and pre-fill form

**Functions updated:**
- `veCreateRequestCard(item, showDeleteBtn, showStatusBtns)` - Added 3rd parameter
- `veRenderPending()` - Pass `showStatusBtns=false`
- `veRenderApplied()` - Pass `showStatusBtns=true`

**Lines added:** ~80

---

## Testing Checklist

- [ ] Build with requests → Applied Changes shows 3 buttons per item
- [ ] Click "✓ Resolved" → Button turns green, "Not Resolved" grays out
- [ ] Click "✗ Not Resolved" → Button turns red, "Resolved" grays out
- [ ] Click active button again → Both buttons return to inactive state
- [ ] Click "📋 Duplicate & Edit" → Form opens
- [ ] Check form has correct category selected
- [ ] Check form has level selected (if Level Design)
- [ ] Check form has text pre-filled
- [ ] Edit text and submit → New pending request created
- [ ] Refresh page → Status resets (expected, not persisted)

---

## Edge Cases

**1. Request has no screenshot:**
- Duplicate still works
- Form opens without screenshot
- User can add screenshot if needed

**2. Request is Legacy category:**
- Duplicate works
- Category selected as Legacy
- All other fields pre-filled

**3. Level Design request:**
- Level dropdown auto-selects correct level
- User can change level if needed

**4. Multiple duplicates:**
- Can duplicate same request multiple times
- Each creates independent new request

---

## Future Enhancements (Not Implemented)

- [ ] Persist status to localStorage
- [ ] Show status counts: "2 resolved, 1 not resolved"
- [ ] Filter applied changes by status
- [ ] Export QA report (CSV/JSON)
- [ ] Analytics: success rate per category

---

## Status: READY TO TEST 🚀

**Refresh browser** and test:

1. **Build with pending requests** → Check Applied Changes
2. **Click "✓ Resolved"** → Verify green + toggle behavior
3. **Click "✗ Not Resolved"** → Verify red + toggle behavior
4. **Click "📋 Duplicate & Edit"** → Verify form opens pre-filled
5. **Edit and submit** → Verify new pending request created

All features are live and ready to use!
