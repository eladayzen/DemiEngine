# Capture Button Flow

## What is the Capture Button?

The **Capture** button is located in the **Live Preview** panel (left side of screen). It takes a screenshot of the currently running game and automatically opens it in the Visual Editor for analysis.

---

## What Happens When You Click Capture?

### Step 1: Screenshot Capture
The system captures the current game screen from the preview iframe:
- Reads the HTML5 canvas element (where the game is drawn)
- Converts it to a PNG image
- Encodes it as base64 text for transmission

### Step 2: Game State Metadata Capture
At the same time, the system reads the current game state from the running game:

**Metadata captured:**
- **Level number** - Which level is currently playing (e.g., Level 1, Level 2)
- **Foundation card** - The current card on the foundation pile (e.g., "7H" = 7 of Hearts)
- **Tableau card count** - How many cards are currently in the tableau (playing area)
- **Draw pile count** - How many cards remain in the draw pile

**Example metadata:**
```json
{
  "level_number": 1,
  "foundation_card": "7H",
  "tableau_count": 5,
  "draw_pile_count": 3
}
```

This metadata is logged to the browser console and stored internally.

### Step 3: Auto-Open Visual Editor
The system automatically:
- Switches to the **Visual Editor** tab
- Opens a new **Request** form
- Selects **Path A** (Positioning & Layout)
- Loads the captured screenshot into the drawing canvas

### Step 4: Ready for Editing
You can now:
- Draw annotations on the screenshot (arrows, boxes, marks)
- Add text notes describing what you want changed
- Submit to Claude for AI analysis

---

## How Claude Uses This Data

When you submit the request via **Path A**, Claude receives:

1. **The screenshot** - Visual of the current game state
2. **Your annotations** - Any marks or notes you added
3. **Game metadata** - Context about what's happening in the game

**Example of what Claude sees:**
```
Game state context: Level: 1, Foundation: 7H, Tableau cards: 5, Draw pile: 3

Operator instruction: Move the top row cards wider apart
```

This context helps Claude understand:
- Which level configuration is being modified
- What the starting state is
- Where the player is in the game (beginning, mid-game, stuck, etc.)

Claude then generates a new layout that matches your request while keeping the game solvable.

---

## Technical Notes

**Metadata Source:** The metadata is read from JavaScript variables in the game's iframe:
- `iframe.contentWindow.currentLevel`
- `iframe.contentWindow.foundation`
- `iframe.contentWindow.tableau`
- `iframe.contentWindow.drawPile`

**Fallback:** If metadata cannot be read (game variables not found), only the screenshot is captured. The system continues working without the metadata.

**Metadata Lifecycle:**
- Captured when Capture button is clicked
- Stored until the form is closed or reset
- Cleared when you cancel or complete the request
- Not reused between different requests

---

## Summary

**Capture button = Screenshot + Game State → Claude**

This gives the AI both visual context (what it looks like) and semantic context (what's actually happening in the game logic), resulting in better, more accurate layout suggestions.
