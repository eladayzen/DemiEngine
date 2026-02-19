# Visual Editor — Build Plan
> Written: 2026-02-19
> Status: PLANNING — not yet started
> Orchestrator: Claude (this session)

---

## What We Are Building

A new "Visual Editor" tab in the existing UI.
The old tabs (Mechanics / Visual / Levels) are **never touched**.

The Visual Editor gives operators two paths to request changes before committing to a Build:

### The Problem It Solves
Operators at a playable ad company have two recurring pain points:
1. **Positioning & scaling** — cards in wrong places, grid too cramped, elements misaligned
2. **Asset changes** — background looks wrong, card back needs a different style

Currently both require writing JSON by hand or re-running full builds to see results.
The Visual Editor removes that friction.

---

## The Two Paths

### Path A — Positioning & Scaling (structural)
For when the operator wants to change **where things are**.

```
1. Upload screenshot of current build
2. Draw annotations on top (arrows, circles, rough positions)
   OR: type rough text → Claude suggests prompts → Nanobanana generates visual target
       → operator picks → can still draw on top of that target
3. Add optional text note
4. Queue the change (don't build yet)
```
→ When ready: Claude Vision reads screenshot + annotations + text → returns config diff → updates form

### Path B — Asset Changes (creative/visual)
For when the operator wants to change **what things look like**.

```
1. Upload screenshot of current build
2. Write rough description ("dark forest background with glowing plants")
3. Claude suggests 3 refined prompts → operator picks one (or edits)
4. Nanobanana generates 2 variations → operator selects reference (async — can work on other changes while waiting)
5. Can draw annotations on the selected reference image
6. Select which assets to replace from asset picker
7. Queue the change
```
→ When ready: original asset + annotated reference → Nanobanana → new asset versions → injected into build

### Universal Drawing Rule
**Any image surface in the tool always has a drawing layer available.**
Doesn't matter if it's an original screenshot, a Nanobanana output, or an externally uploaded image.
Drawing is always optional, always addable, never forced.

---

## The Change Queue

Changes stack up before a single Build:

```
[Change #1] Path A — "spread top row wider"     [Ready]
[Change #2] Path B — "dark forest background"   [Awaiting Nanobanana...]
[Change #3] Path A — "foundation card lower"    [Ready]
[Change #4] Path B — "card back texture"        [Pick a reference]
                    ↓
              [Build Once]
```

Each queue item has states:
`Drafting` → `Processing` → `Awaiting Selection` → `Annotating` → `Ready` → `Built`

Nanobanana calls are async — operator doesn't block. They submit and come back.

---

## API Contract (agreed interface between all agents)

### New endpoints

#### `POST /api/nanobanana/enhance-prompt`
```json
Request:  { "rough_prompt": "str", "screenshot": "base64 str" }
Response: { "suggestions": ["str", "str", "str"] }
```
Claude Vision sees current screenshot + rough intent → returns 3 refined prompts.

---

#### `POST /api/nanobanana/generate`
```json
Request:  { "prompt": "str", "reference_image": "base64 str | null", "num_variations": 2 }
Response: { "images": ["base64 str", "base64 str"] }
```
Calls Gemini image API. Image-to-image if reference provided, text-to-image if not.
Default 2 variations for MVP.

---

#### `POST /api/visual/layout`  (Path A final step)
```json
Request: {
  "screenshot": "base64 str",
  "annotations": "base64 str | null",
  "nanobanana_reference": "base64 str | null",
  "text_note": "str | null",
  "level_index": 0
}
Response: { "layout": { ...LevelLayout dict... } }
```
Claude Vision: compares inputs → returns full LevelLayout. Same pattern as M6.

---

#### `GET /api/assets/list`
```json
Response: {
  "assets": [
    { "name": "background", "preview": "base64 str", "description": "Full background image" },
    { "name": "card_back",  "preview": "base64 str", "description": "Card back face" },
    { "name": "felt",       "preview": "base64 str", "description": "Table surface texture" }
  ]
}
```
Returns swappable asset slots with current previews (or placeholder if none set).

---

#### `POST /api/assets/replace`  (Path B final step)
```json
Request: {
  "asset_names": ["background", "card_back"],
  "reference_image": "base64 str",
  "annotations": "base64 str | null"
}
Response: { "updated_assets": { "background": "base64 str", "card_back": "base64 str" } }
```
For each asset: original + annotated reference → Gemini image-to-image → new version.

---

### Config schema additions
All three new fields added to `visual` config, all default `null`:
```json
"visual": {
  "...existing fields...",
  "background_image": null,
  "card_back_image": null,
  "felt_image": null
}
```
Engine uses code-drawn fallback when null. Zero breaking change to existing builds.

---

### Engine behavior (new)
```js
// Background
if (CONFIG.visual.background_image) {
  bgSprite = new PIXI.Sprite(PIXI.Texture.from(CONFIG.visual.background_image));
} else {
  // existing: draw colored rectangle
}

// Card back (when rendering a face-down card)
if (CONFIG.visual.card_back_image) {
  // use PIXI.Sprite texture
} else {
  // existing: draw rectangle with pattern
}
```

---

## Files Changed Per Area

| Area | Files | Notes |
|------|-------|-------|
| Backend | `app.py`, new `gemini.py` | 5 new endpoints + Gemini SDK |
| Frontend | `static/index.html` | New tab appended — old tabs untouched |
| Engine | `static/engine_template.html`, `static/engine_test.html` | Sprite slots with null fallback |
| Schema | `schemas.py` | 3 new optional visual fields |
| Config | `defaults/visual.json` | Add null defaults for 3 new fields |
| Dependencies | `requirements.txt` | Add `google-genai` |

---

## Multi-Agent Approach

### Should we split into agents?

**When YES:**
- Work has clearly separated files with zero overlap
- Each task is large enough to justify the overhead
- You're comfortable merging branches at the end

**When NO:**
- Tasks are small (< 1 hour equivalent work)
- High interdependency (one agent needs the other's output to proceed)
- Risk of diverging on the same file

**Verdict for this build:** The three areas (Backend / Frontend / Engine) have zero file overlap.
Splitting is safe. But we only split if the user wants speed over simplicity.

---

### Agent Definitions (if splitting)

#### Agent 1 — Backend
**Branch:** `feature/visual-editor-backend`
**Files:** `app.py`, `gemini.py` (new), `schemas.py`, `defaults/visual.json`, `requirements.txt`
**Task:** Implement all 5 new endpoints per the API contract above.

**Can do autonomously:**
- Write all endpoint logic
- Add Gemini SDK calls
- Add Pydantic models
- Add schema fields

**Must check with orchestrator before:**
- Changing any existing endpoint (not just adding)
- Changing the API contract (request/response shape) — frontend agent depends on it
- Installing packages beyond `google-genai`
- Deleting or renaming any existing function

---

#### Agent 2 — Frontend
**Branch:** `feature/visual-editor-frontend`
**Files:** `static/index.html` (new tab section only — append, never touch existing tabs)

**Can do autonomously:**
- Build the Visual Editor tab UI
- Implement change queue logic
- Implement canvas drawing layer
- Call all new API endpoints per contract above

**Must check with orchestrator before:**
- Touching the Mechanics / Visual / Levels tabs or any existing JS functions
- Adding new JS libraries (CDN or otherwise)
- Changing any existing `id=` or `class=` attribute in the old tabs
- Making the Visual Editor tab the default active tab

---

#### Agent 3 — Engine
**Branch:** `feature/visual-editor-engine`
**Files:** `static/engine_template.html`, `static/engine_test.html`

**Can do autonomously:**
- Add sprite rendering for background / card_back / felt with null fallback
- Add the 3 new fields to the embedded test config in engine_test.html (set to null)

**Must check with orchestrator before:**
- Changing any gameplay logic (move validation, win/lose, animations)
- Changing any existing config field names
- Adding new PixiJS plugins or external scripts
- Modifying the scene graph structure beyond adding new sprites

---

### Orchestration Rules

1. **Agent 3 starts first** — engine change is independent and lowest risk.
   Agents 1 and 2 can start simultaneously with Agent 3.

2. **API contract is frozen** once agents start.
   Any contract change requires orchestrator to pause both Agent 1 and Agent 2,
   agree on the change, then resume.

3. **No agent pushes to git** without orchestrator sign-off.
   Each agent commits locally to its branch only.

4. **Merge order:**
   Agent 3 (engine) → Agent 1 (backend) → Agent 2 (frontend) → integration test → merge to main

5. **Integration test** (done by orchestrator after merge):
   - Server starts cleanly
   - Old tabs still work — generate a build, preview it
   - New tab visible and loads
   - Path A: upload screenshot, get layout back
   - Path B: enhance prompt, generate Nanobanana image, replace an asset

6. **If an agent hits a blocker** it stops and reports to orchestrator.
   It does NOT improvise outside its file scope.

---

## Setup Steps (user must do once before building)

1. Install new dependency:
   ```
   pip install google-genai
   ```

2. Get a Google AI Studio API key:
   - Go to: https://aistudio.google.com/apikey
   - Create a key
   - Add to `.env`:
     ```
     GEMINI_API_KEY=your-key-here
     ```

3. (If using multi-agent) Set up git worktrees:
   ```bash
   cd C:\Tests\PlayablePrtoto
   git worktree add ../PlayablePrtoto-backend feature/visual-editor-backend
   git worktree add ../PlayablePrtoto-frontend feature/visual-editor-frontend
   git worktree add ../PlayablePrtoto-engine feature/visual-editor-engine
   ```
   Then open a new terminal in each folder and run `claude` in each.

---

## Build Order (single-agent fallback)

If we don't split into agents, do it in this order:
1. `schemas.py` + `defaults/visual.json` — schema additions (5 min)
2. `gemini.py` — Gemini SDK wrapper (30 min)
3. `app.py` — 5 new endpoints (45 min)
4. `engine_template.html` + `engine_test.html` — sprite slots (20 min)
5. `static/index.html` — Visual Editor tab (90 min)
6. Integration test

---

## What Is NOT in This Build (future)

- localStorage save for the change queue
- Export/import full change queue as JSON
- Per-level visual config (currently global)
- More asset slots beyond background / card_back / felt
- Video/animation assets
- Path B for non-image assets (fonts, colors)
- Undo/redo within the change queue
