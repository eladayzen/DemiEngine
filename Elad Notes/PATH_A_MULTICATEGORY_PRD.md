# Path A Multi-Category System — PRD

## Executive Summary

Transform Path A from a single-purpose "Positioning & Layout" tool into a **multi-category request system** that handles all types of gameplay and visual changes. Each request is categorized, gets category-specific Claude prompting, and includes conflict detection for level-specific changes.

---

## Current State vs. Proposed State

### Current (Path A)
- Single purpose: "Positioning & Layout"
- All requests use same system prompt
- No category tracking
- No level tracking
- No conflict detection

### Proposed (Multi-Category Path A)
- **5 categories:** Game Design, Level Design, Graphics & UI, Animation & Polish, Legacy
- Each category has **tailored system prompt** for Claude
- **Category locked after Claude reasoning** (prevents accidental changes)
- **Level tracking** for Level Design requests
- **Conflict detection** warns about duplicate level requests
- **Scope awareness:** Global vs. Level-specific changes

---

## The 5 Categories

| Icon | Category | Scope | Description | Uses Tool? |
|------|----------|-------|-------------|------------|
| 🎮 | **Game Design** | Global | Core mechanics, rules, game-wide settings | ❌ No |
| 🎯 | **Level Design** | Level-specific | Puzzle layouts, card positions, foundation, draw pile | ✅ Yes (`generate_level_layout`) |
| 🎨 | **Graphics & UI** | Global | Colors, fonts, UI elements, visual styling | ❌ No |
| ✨ | **Animation & Polish** | Global | Motion, timing, juice, visual effects | ❌ No |
| 📝 | **Legacy** | Variable | Free-form requests (uses current prompting) | ✅ Yes (`generate_level_layout`) |

---

## Category Details & Prompting Structure

### 🎮 Game Design (Global)

**When to use:**
- Change game rules (e.g., "allow suit matching", "disable wrapping")
- Modify timer behavior
- Change scoring mechanics
- Adjust difficulty curve across all levels

**System Prompt:**
```
You are a game designer for a simplified solitaire card game.

GAME RULES (current):
- Foundation is one face-up card. Player taps tableau cards to play onto it.
- Valid move: card value is exactly ±1 from foundation value
- Values wrap: K↔A are adjacent (K→A and A→K both valid)
- No suit matching — only value matters
- Value order: A 2 3 4 5 6 7 8 9 10 J Q K (wraps to A)
- After a tableau card is played, next face-down card in that column flips face-up
- Win = all tableau cards played. Lose = no valid moves and draw pile empty

YOUR TASK:
The operator wants to modify CORE GAME MECHANICS that affect ALL levels.

Read the request carefully and explain:
1. What specific rule/mechanic they want to change
2. How this affects gameplay across all levels
3. What implementation changes are needed (specific config fields to modify)
4. Any gameplay implications or balance concerns

Be specific about which config fields need to change (e.g., "Set mechanics.allow_suit_matching to true").

DO NOT use the generate_level_layout tool — this is a mechanics change, not a level layout change.
```

**Output format:** Text reasoning only (no tool use)

**Example requests:**
- "Disable wrapping — Aces and Kings should NOT connect"
- "Add a 30-second timer per level"
- "Make it so only same-suit matches are valid"

---

### 🎯 Level Design (Level-specific)

**When to use:**
- Modify specific level puzzles
- Change card positions for a level
- Add a new level
- Adjust difficulty of one level

**System Prompt:**
```
You are a level designer for a simplified solitaire card game.

GAME RULES:
- Foundation is one face-up card. Player taps tableau cards to play onto it.
- Valid move: card value is exactly ±1 from foundation value
- Values wrap: K↔A are adjacent (K→A and A→K both valid)
- No suit matching — only value matters
- Value order: A 2 3 4 5 6 7 8 9 10 J Q K (wraps to A)
- After a tableau card is played, next face-down card in that column flips face-up
- Win = all tableau cards played. Lose = no valid moves and draw pile empty

CARD CODES:
- Values: A 2 3 4 5 6 7 8 9 10 J Q K
- Suits: H D C S (Hearts, Diamonds, Clubs, Spades)
- Examples: "7H", "10S", "AS", "KD"

LAYOUT FORMAT:
- col: 0-based column index, left to right
- row: 0 = top face-up card, 1+ = face-down cards beneath
- face_up: true for row=0, false for row>0 (unless specified otherwise)

READING DRAWN ANNOTATIONS:
When the screenshot contains operator-drawn marks (arrows, boxes, lines, X, circles):
  → Arrow = move card/column from tail to arrow point
  □ Box = resize, regroup, or restructure enclosed area
  ✕ X mark = remove this card/column
  + or circle = add something here
  Line between A→B = relationship or path from A to B
  Number label = set column/row to that count

YOUR TASK:
The operator is modifying a SPECIFIC LEVEL (Level {level_number}).

1. Read all visual marks and text instructions carefully
2. Work out the FULL solve_sequence — verify every move is valid ±1 before proceeding
3. Use generate_level_layout tool to output the updated layout
4. Keep it simple: 3-8 tableau cards, max 2 face-down rows per column
5. DO NOT include grid — auto-computed by server

When outputting reasoning:
- First describe what you see in the screenshot/annotations
- Explain what changes you're making to THIS level
- Confirm the level is still solvable
```

**Output format:** Text reasoning + `generate_level_layout` tool use

**Example requests:**
- "Add another column with 3H face-down under 4S"
- "Remove the rightmost column"
- "Add a new Level 6 — medium difficulty, 6 cards, foundation 8D"

**Special case: "Add new level"**
- User may write "add a new level 6" or "create level 4"
- System detects level number from text or asks user via dropdown
- Creates a fresh layout for that level index

---

### 🎨 Graphics & UI (Global)

**When to use:**
- Change colors, fonts, or visual styling
- Modify UI layout (buttons, text positions)
- Adjust card appearance (size, border, shadow)
- Change background color or texture

**System Prompt:**
```
You are a UI/UX designer for a mobile card game playable ad.

CURRENT VISUAL CONFIG STRUCTURE:
- Colors: background_color, card_back_color, table_felt_color, card_border_color, foundation_border_color
- Text: font_family, font_color, title_font_size
- Card styling: card_border_width, card_corner_radius, card_shadow
- UI elements: button styles, text positions

YOUR TASK:
The operator wants to modify VISUAL/UI elements that affect the ENTIRE game.

Read the request and screenshot carefully, then explain:
1. What specific visual elements they want to change
2. Which config fields need to be updated (be specific: "visual.card_border_color")
3. Exact values to use (colors as hex codes, sizes as pixels)
4. Any visual hierarchy or accessibility concerns

DO NOT use the generate_level_layout tool — this is a styling change, not a level layout change.

If the request involves reference images or Nanobanana outputs, describe how the visual style should be adapted.
```

**Output format:** Text reasoning only (no tool use)

**Example requests:**
- "Make all cards have rounded corners with 8px radius"
- "Change the background color to dark green #1a472a"
- "Use the style from @Image01 — brighter colors and bold text"

---

### ✨ Animation & Polish (Global)

**When to use:**
- Add or modify animations (card flip, slide, bounce)
- Adjust timing or easing
- Add particle effects or visual juice
- Change transition speeds

**System Prompt:**
```
You are a motion designer for a mobile card game playable ad.

CURRENT ANIMATION CONFIG:
- Card flip speed, slide timing, bounce effects
- Particle systems (sparkles, confetti, etc.)
- Transition easing functions
- Visual feedback (tap ripple, success animations)

YOUR TASK:
The operator wants to add or modify ANIMATION/MOTION that affects the ENTIRE game.

Read the request carefully and explain:
1. What specific animation or effect they want
2. Where it should appear (which game event triggers it)
3. Technical approach (CSS animation, particle system, timing function)
4. Performance implications (mobile devices have limits)

DO NOT use the generate_level_layout tool — this is an animation change, not a level layout change.

Focus on juice and game feel — what makes interactions satisfying.
```

**Output format:** Text reasoning only (no tool use)

**Example requests:**
- "Add a bounce animation when cards are played"
- "Make the victory animation more exciting with confetti"
- "Slow down card flip speed to 300ms"

---

### 📝 Legacy (Variable Scope)

**When to use:**
- Requests that don't fit other categories
- Mixed requests (e.g., "change level 3 AND add animation")
- Operator explicitly wants free-form handling

**System Prompt:**
```
[Uses the current VISUAL_LAYOUT_SYSTEM prompt — unchanged from current implementation]

You are a level designer for a simplified solitaire card game.

You receive a screenshot of the current build and optional instructions.

[Full current prompt with annotation reading, card codes, grid coordinates...]

Use generate_level_layout tool when the request involves layout changes.
For non-layout requests, provide text reasoning only.
```

**Output format:** Text reasoning + optional `generate_level_layout` tool use (auto mode)

**Example requests:**
- "Make it look more fun"
- "Improve level 2 and change the button color"
- Any ambiguous or multi-category request

---

## User Flow

### Step 1: Category Selection

When user clicks "+ New Request", they see 5 category buttons:

```
┌─────────────────────────────────────────────────────┐
│ What do you want to change?                        │
├─────────────────────────────────────────────────────┤
│                                                     │
│  🎮 Game Design                   [Always Global]  │
│  Core mechanics, rules, game-wide settings         │
│                                                     │
│  🎯 Level Design                  [Select level ▾] │
│  Puzzle layouts, card positions for specific level │
│                                                     │
│  🎨 Graphics & UI                 [Always Global]  │
│  Colors, fonts, UI elements, visual styling        │
│                                                     │
│  ✨ Animation & Polish           [Always Global]  │
│  Motion, timing, juice, visual effects             │
│                                                     │
│  📝 Legacy                        [Auto-detected]  │
│  Free-form requests (advanced users)               │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### Step 2: Level Selection (Level Design only)

If user selects **Level Design**, a dropdown appears:

```
Which level are you modifying?
┌──────────────────────┐
│ Level 1            ▾ │  ← Dropdown with all existing levels
│ Level 2              │     PLUS "Add new level" option
│ Level 3              │
│ ─────────────────    │
│ + Add new level      │
└──────────────────────┘
```

**Special case:** If user selects "Add new level":
- Next available level number auto-selected (e.g., if 3 levels exist, auto-select "Level 4")
- User can still type in request box: "actually make this level 6" and Claude will detect it

### Step 3: Rest of Form (Same as Current)

- Screenshot upload (if applicable)
- Drawing tools (if applicable)
- Reference images (if applicable)
- Text note area
- Submit button

### Step 4: Claude Processes Request

Backend:
1. Receives: category, level_number (if Level Design), screenshot, annotations, text
2. Selects correct system prompt based on category
3. Calls Claude with category-specific prompt
4. Claude returns reasoning + optional tool use
5. **Category is now LOCKED** (cannot be changed in edit mode)

### Step 5: Request Appears in Pending

Shows:
- Category badge (🎮 Game Design, 🎯 Level 3, etc.)
- Claude's reasoning (simple language summary)
- Complexity indicator (if applicable)
- Level conflict warning (if another request already targets same level)

**Example Pending Request Display:**

```
┌────────────────────────────────────────────────────┐
│ 🎯 Level 3  │ moderate                             │
│────────────────────────────────────────────────────│
│ I've moved the 4S column to the right and added a  │
│ face-down 3H underneath it. The level is still     │
│ solvable by playing 4S→5H→6D→7C.                   │
│                                                    │
│ ⚠️ Note: Another pending request also modifies    │
│    Level 3. Consider resolving one first.         │
│────────────────────────────────────────────────────│
│ [View Details] [Edit] [Delete]                    │
└────────────────────────────────────────────────────┘
```

---

## Level Detection Logic

**Priority order for detecting level number:**

1. **Explicit user selection** (Level Design dropdown)
2. **Game metadata** (if Capture button was used, metadata contains `level_number`)
3. **Text parsing** (scan request text for "level 3", "Level 1", "lv2", etc.)
4. **Claude inference** (ask Claude to detect from screenshot + text)
5. **Default fallback** (assume Level 1 if detection fails)

**Backend implementation:**

```python
def detect_level_number(
    category: str,
    level_index: Optional[int],  # from dropdown
    game_metadata: Optional[dict],  # from Capture
    text_note: Optional[str]  # user's text
) -> int:
    # Priority 1: Explicit selection
    if level_index is not None:
        return level_index

    # Priority 2: Game metadata
    if game_metadata and "level_number" in game_metadata:
        return game_metadata["level_number"]

    # Priority 3: Text parsing
    if text_note:
        import re
        match = re.search(r'\b(?:level|lv)\s*(\d+)\b', text_note, re.IGNORECASE)
        if match:
            return int(match.group(1))

    # Priority 4: Claude inference (add to system prompt)
    # Priority 5: Default
    return 1
```

---

## Conflict Detection

### What is a conflict?

**Critical conflict:**
- Two or more pending requests targeting **same level number** with Level Design category
- Example: Request #1 changes Level 2 layout, Request #2 also changes Level 2 layout

**Informational (not critical):**
- Multiple Graphics & UI requests (can be combined)
- Multiple Animation requests (can be combined)
- Game Design + Level Design (different scopes, usually OK)

### Visual Warning (Phase 1 — Simple)

When a conflict is detected, show warning **below the pending request**:

```
⚠️ Another pending request also modifies Level 3.
   These requests may conflict when applied together.
```

### Advisory Popup (When Clicking Build)

If critical conflicts exist when user clicks "Build Ad with All Changes":

```
┌─────────────────────────────────────────────────────┐
│ ⚠️ Potential Conflicts Detected                     │
├─────────────────────────────────────────────────────┤
│                                                     │
│ You have multiple requests targeting the same      │
│ level(s):                                           │
│                                                     │
│ • Level 3: 2 pending requests                      │
│                                                     │
│ When both are applied, the second request may      │
│ overwrite changes from the first.                  │
│                                                     │
│ Recommendation: Review these requests and consider │
│ deleting duplicates before building.               │
│                                                     │
│ [Review Requests] [Build Anyway]                   │
└─────────────────────────────────────────────────────┘
```

**Tone:** Advisory, educational, NOT blocking. User can always proceed.

---

## Technical Implementation

### Backend Changes (app.py)

**1. Update `VisualLayoutRequest` model:**

```python
class VisualLayoutRequest(BaseModel):
    screenshot: Optional[str] = None
    annotations: Optional[str] = None
    nanobanana_reference: Optional[str] = None
    reference_images: Optional[list[str]] = None
    text_note: Optional[str] = None
    has_drawing: bool = False
    level_index: Optional[int] = None  # NEW: from dropdown or auto-detected
    game_metadata: Optional[dict] = None
    category: str = "legacy"  # NEW: game_design, level_design, graphics_ui, animation, legacy
```

**2. Create category-specific system prompts:**

```python
CATEGORY_PROMPTS = {
    "game_design": GAME_DESIGN_SYSTEM,
    "level_design": LEVEL_DESIGN_SYSTEM,
    "graphics_ui": GRAPHICS_UI_SYSTEM,
    "animation": ANIMATION_SYSTEM,
    "legacy": VISUAL_LAYOUT_SYSTEM,  # current prompt
}
```

**3. Update `/api/visual/layout` endpoint:**

```python
@app.post("/api/visual/layout")
async def visual_layout(req: VisualLayoutRequest):
    # Detect level number (if Level Design category)
    level_number = None
    if req.category == "level_design":
        level_number = detect_level_number(
            req.category,
            req.level_index,
            req.game_metadata,
            req.text_note
        )

    # Select system prompt based on category
    system_prompt = CATEGORY_PROMPTS.get(req.category, CATEGORY_PROMPTS["legacy"])

    # Inject level number into prompt if applicable
    if level_number is not None:
        system_prompt = system_prompt.replace("{level_number}", str(level_number))

    # Decide tool usage based on category
    if req.category in ("level_design", "legacy"):
        tools = [GAMEPLAY_TOOL]
        tool_choice = {"type": "auto"}
    else:
        tools = []
        tool_choice = None

    # Call Claude
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=2048,
        system=system_prompt,
        tools=tools if tools else None,
        tool_choice=tool_choice,
        messages=[{"role": "user", "content": content}]
    )

    # Extract reasoning and tool result
    # Return both + detected level_number
    return {
        "layout": layout_dict if tool_result else None,
        "reasoning": reasoning_simple,
        "complexity": complexity,
        "category": req.category,
        "level_number": level_number,
    }
```

### Frontend Changes (index.html)

**1. Update category selection UI:**

Replace current single "Positioning & Layout" button with 5 category buttons:

```html
<div id="ve-step-category">
  <div class="ve-step-header">
    <span class="ve-step-num">1</span> What do you want to change?
  </div>

  <div class="ve-category-btns">
    <button class="ve-category-btn" onclick="veSelectCategory('game_design')">
      <div class="ve-cat-icon">🎮</div>
      <div class="ve-cat-title">Game Design</div>
      <div class="ve-cat-scope">Global</div>
      <div class="ve-cat-desc">Core mechanics, rules, game-wide settings</div>
    </button>

    <button class="ve-category-btn" onclick="veSelectCategory('level_design')">
      <div class="ve-cat-icon">🎯</div>
      <div class="ve-cat-title">Level Design</div>
      <div class="ve-cat-scope">Level-specific</div>
      <div class="ve-cat-desc">Puzzle layouts, card positions for specific level</div>
    </button>

    <!-- ... other 3 categories ... -->
  </div>
</div>
```

**2. Add level selection dropdown (shown only for Level Design):**

```html
<div id="ve-step-level" style="display:none">
  <div class="ve-label">Which level are you modifying?</div>
  <select id="ve-level-select">
    <option value="1">Level 1</option>
    <option value="2">Level 2</option>
    <option value="3">Level 3</option>
    <option value="-1">➕ Add new level</option>
  </select>
</div>
```

**3. Update request submission:**

```javascript
function veSubmitRequest() {
  var category = veSelectedCategory;  // 'game_design', 'level_design', etc.
  var levelIndex = null;

  if (category === 'level_design') {
    levelIndex = parseInt(document.getElementById('ve-level-select').value);
  }

  var payload = {
    category: category,
    level_index: levelIndex,
    screenshot: veScreenshot,
    annotations: veAnnotations,
    text_note: document.getElementById('ve-text-note').value,
    // ... rest of fields
  };

  fetch('/api/visual/layout', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  })
  .then(response => response.json())
  .then(result => {
    // Store result with category and level_number
    vePendingRequests.push({
      id: Date.now(),
      category: result.category,
      level_number: result.level_number,
      reasoning: result.reasoning.simple,
      complexity: result.reasoning.complexity,
      layout: result.layout,
      locked: true,  // Category is now locked
    });

    // Check for conflicts
    veCheckConflicts();

    // Re-render pending list
    veRenderPending();
  });
}
```

**4. Conflict detection function:**

```javascript
function veCheckConflicts() {
  var levelCounts = {};

  vePendingRequests.forEach(function(req) {
    if (req.category === 'level_design' && req.level_number) {
      var key = 'level_' + req.level_number;
      levelCounts[key] = (levelCounts[key] || 0) + 1;
    }
  });

  // Mark requests with conflicts
  vePendingRequests.forEach(function(req) {
    if (req.category === 'level_design' && req.level_number) {
      var key = 'level_' + req.level_number;
      req.has_conflict = levelCounts[key] > 1;
    }
  });
}
```

**5. Render pending requests with category badges + conflict warnings:**

```javascript
function veRenderPending() {
  var list = document.getElementById('ve-pending-list');
  list.innerHTML = '';

  vePendingRequests.forEach(function(req) {
    var li = document.createElement('li');

    // Category badge
    var badge = '';
    if (req.category === 'game_design') badge = '🎮 Game Design (Global)';
    else if (req.category === 'level_design') badge = '🎯 Level ' + req.level_number;
    else if (req.category === 'graphics_ui') badge = '🎨 Graphics & UI (Global)';
    else if (req.category === 'animation') badge = '✨ Animation (Global)';
    else badge = '📝 Legacy';

    li.innerHTML = `
      <div style="flex:1">
        <div class="ve-badge">${badge}</div>
        <div class="ve-badge ${req.complexity}">${req.complexity}</div>
        <div style="margin-top:8px">${req.reasoning}</div>
        ${req.has_conflict ? '<div class="ve-warning">⚠️ Another pending request also modifies this level</div>' : ''}
      </div>
      <button onclick="veDeleteRequest(${req.id})">Delete</button>
    `;

    list.appendChild(li);
  });
}
```

**6. Build button warning popup:**

```javascript
function onGenerate() {
  // Check for critical conflicts
  var conflicts = {};
  vePendingRequests.forEach(function(req) {
    if (req.category === 'level_design' && req.level_number) {
      var key = req.level_number;
      conflicts[key] = (conflicts[key] || 0) + 1;
    }
  });

  var criticalConflicts = Object.keys(conflicts).filter(k => conflicts[k] > 1);

  if (criticalConflicts.length > 0) {
    var msg = '⚠️ Potential Conflicts Detected\n\n';
    msg += 'You have multiple requests targeting the same level(s):\n\n';
    criticalConflicts.forEach(function(lvl) {
      msg += '• Level ' + lvl + ': ' + conflicts[lvl] + ' pending requests\n';
    });
    msg += '\nWhen both are applied, the second request may overwrite changes from the first.\n\n';
    msg += 'Recommendation: Review these requests and consider deleting duplicates before building.\n\n';
    msg += 'Do you want to continue building anyway?';

    if (!confirm(msg)) {
      return;  // User cancelled
    }
  }

  // Continue with build...
  buildWithPendingChanges();
}
```

---

## Decision Points & Open Questions

### ✅ Decisions Made (Ready to Implement)

1. **5 categories** with specific scoping (Global vs Level-specific)
2. **Category locking** happens after Claude reasoning (cannot edit category after submission)
3. **Level detection** uses priority system (dropdown > metadata > text > Claude > default)
4. **Conflict detection** Phase 1 = visual warnings only (advisory popup on Build)
5. **Warning UX tone** = advisory, educational, never blocking
6. **Tool usage** = only Level Design and Legacy use `generate_level_layout`, others text-only

### ⚠️ Decisions Needed Before Implementation

**Question 1: Analytics & Historical Tracking**

User said: "I am not sure about it yet"

**Options:**
- **A) Skip analytics entirely in Phase 1** — Just do categories + conflict detection, no tracking
- **B) Build infrastructure but hide UI** — Add resolved/unresolved tracking to data model, but don't show analytics UI yet
- **C) Build minimal analytics** — Just "Resolved / Not Resolved / Duplicate" buttons, no graphs or pattern detection

**Recommendation:** Option A — Skip analytics in Phase 1. Focus on core category system. Add analytics later if needed.

---

**Question 2: Request Status Lifecycle**

Do pending requests become "Applied" after a build, or do they disappear?

**Options:**
- **A) Current behavior** — Pending requests clear after build, shown in Applied Changes (grouped by build)
- **B) Persistent tracking** — Requests stay in "Applied" list forever with status buttons (Resolved / Not Resolved)
- **C) Hybrid** — Requests move to Applied but can be marked as Resolved to hide them

**Recommendation:** Option A for Phase 1 — Keep current behavior. Simpler, less complexity.

---

**Question 3: "Add New Level" Workflow**

When user selects "Add new level", should we:

**Options:**
- **A) Auto-number** — Automatically assign next level number (e.g., if 3 levels exist, create Level 4)
- **B) Ask user** — Show input field: "Enter new level number: __"
- **C) Claude decides** — Let Claude read the request and decide the level number

**Recommendation:** Option A — Auto-number. User can override in text if needed ("actually make this level 6").

---

**Question 4: Edit Mode for Locked Categories**

User submits request → Claude processes → Category is locked.

If user clicks "Edit" on a pending request, can they:

**Options:**
- **A) Only edit text/images** — Category stays locked, level number stays locked
- **B) Full re-edit** — Delete and recreate from scratch
- **C) No edit at all** — Only Delete + Create New

**Recommendation:** Option C for Phase 1 — No edit, only delete. Simpler, avoids edge cases.

---

### 📊 Summary of Open Decisions

| Decision | Status | Options | Blocker for Phase 1? |
|----------|--------|---------|----------------------|
| Analytics | ⚠️ Open | A: Skip / B: Build hidden / C: Minimal | ❌ No — can skip |
| Request lifecycle | ⚠️ Open | A: Current / B: Persistent / C: Hybrid | ❌ No — keep current |
| Add new level | ⚠️ Open | A: Auto / B: Ask / C: Claude | ❌ No — use auto |
| Edit locked requests | ⚠️ Open | A: Partial / B: Full / C: None | ❌ No — use delete-only |

**None of these are blockers.** We can implement Phase 1 with recommended defaults and adjust later.

---

## Implementation Checklist

### Backend (app.py)

- [ ] Add `category` and `level_number` fields to `VisualLayoutRequest` model
- [ ] Create 5 category-specific system prompts (constants)
- [ ] Implement `detect_level_number()` function (priority logic)
- [ ] Update `/api/visual/layout` to select prompt based on category
- [ ] Adjust tool usage based on category (Level Design/Legacy only)
- [ ] Return `category` and `level_number` in response

### Frontend (index.html)

- [ ] Create 5-category selection UI (replace single Path A button)
- [ ] Add level dropdown (shown only for Level Design)
- [ ] Update `veSelectCategory()` function
- [ ] Update `veSubmitRequest()` to include category + level_index
- [ ] Implement `veCheckConflicts()` function
- [ ] Update `veRenderPending()` to show category badges + level number
- [ ] Add conflict warning display below pending requests
- [ ] Update Build button to show advisory popup if conflicts detected
- [ ] Lock category after submission (disable category change in edit mode)

### Testing

- [ ] Test each category with sample requests
- [ ] Verify Level Design detects level number correctly
- [ ] Verify conflict detection triggers for duplicate level requests
- [ ] Verify advisory popup appears when building with conflicts
- [ ] Verify categories are locked after Claude reasoning
- [ ] Verify "Add new level" auto-numbers correctly

---

## Success Metrics

**Phase 1 goals:**

1. ✅ Users can categorize requests accurately (< 5% miscategorization)
2. ✅ Level Design requests correctly detect target level (> 90% accuracy)
3. ✅ Conflict warnings prevent accidental overwrites (user feedback)
4. ✅ Category-specific prompts improve Claude output quality (qualitative review)
5. ✅ No increase in user friction (time to submit request stays same)

**Phase 2 goals (if we build analytics):**

- Users can mark requests as Resolved/Not Resolved
- System tracks success rate per category
- Historical view shows patterns over time
