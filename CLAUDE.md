# Playable Ad Generator — Project Context

> This file is auto-read by Claude Code at session start.
> Keep it updated at the end of every session or major decision.

---

## What This Project Is

A tool that generates configurable HTML5 solitaire playable ads.
The user (non-technical game designer) tweaks JSON configs → clicks Generate → gets a self-contained HTML5 ad file ready for AppLovin/MRAID networks.

**Location:** `C:\Tests\PlayablePrtoto`
**Python:** Use `py` (not `python` or `python3`) — Python 3.10.2 is at `C:\Python310`
**Run server:** `py -m uvicorn app:app --port 8000` from project folder
**Framework:** FastAPI backend, PixiJS v7 frontend engine

---

## Milestone Status

| Milestone | Status | Notes |
|-----------|--------|-------|
| M1 — Folder structure + FastAPI skeleton | ✅ Done | `app.py`, `launch.py`, `requirements.txt` |
| M2 — Schemas (Pydantic) + default JSONs | ✅ Done | `schemas.py`, `defaults/` folder |
| M3 — API endpoints (randomize, generate, runs) | ✅ Done | All routes in `app.py`, smoke tested |
| M4/M5 — PixiJS engine + Config UI | ✅ Done | `static/engine_template.html`, `static/engine_test.html`, `static/index.html` |
| M6 — Claude AI integration | ✅ Done | `POST /api/describe/gameplay` — free-text → LevelLayout via tool use |
| M7 — Polish + next features | ⏳ Next | See backlog below |

---

## Key Decisions (locked in — do not revisit without user)

- **Renderer:** PixiJS v7 (WebGL with Canvas fallback) — NOT raw WebGL, NOT Canvas 2D alone
- **Card flip:** scaleX 1→0→1 (swap texture at midpoint) with slight scaleY dip for feel
- **File size target:** under 5MB total (PixiJS v7 minified ~450KB)
- **MRAID:** v2.0 compliant, all CTAs use `mraid.open(url)` with `window.open` fallback
- **No image files** — all cards drawn with PixiJS Graphics (rectangles, text, suit symbols)
- **Wwise/Unity:** completely off the table for this project
- **Python launcher:** always use `py` not `python`

---

## Engine Spec (M4/M5 — ready to build)

### Output files
- `static/engine_template.html` — has `__GAME_CONFIG__` placeholder, used by M6 pipeline
- `static/engine_test.html` — same engine with default config embedded, open in browser to test

### Internal resolution
390 × 844 portrait. PixiJS scales to fill viewport maintaining aspect ratio.

### Card grid
Cards have explicit `col` / `row` positions in JSON — enables any shape (pyramid, diamond, L-shape, etc.)

### Layout (top to bottom)
```
[HUD: Level X/Y, cards left]   ← hidden unless testing_mode: true     y=0–88
[Tableau: col/row grid]                                                 y=155+
[Foundation card — center]                                              y=550
[Draw pile — BOTTOM LEFT]       ← hidden if show_draw_pile: false       y=690
```

### Scene graph
```
app.stage
  └── gameContainer
        ├── bgSprite
        ├── feltSprite
        ├── tableauContainer
        ├── foundationSlot
        ├── foundationCard
        ├── drawPileContainer
        ├── hudContainer        (hidden unless testing_mode: true)
        ├── flyingCard          (renders on top during animation)
        └── overlayContainer    (win/fail/end screens)
```

### "Juicy" effects
- GlowFilter pulsing on valid move targets
- Card flip: scaleX tween + scaleY dip
- Card land: spring bounce overshoot
- Win: ParticleContainer confetti burst
- Fail: screen shake (offset gameContainer)
- Closed→open reveal: flip animation

### Gameplay (simplified solitaire)
- Foundation: one face-up card (the target)
- Tap a face-up tableau card that is ±1 value (wraps K↔A, no suit matching)
- Card flies to foundation → becomes new foundation
- First closed card in tableau flips open after each play
- Draw pile (bottom left): tap to change foundation to next draw card
- Win: all tableau cards played
- Lose: no valid moves + draw pile exhausted

```js
const VALS = ['A','2','3','4','5','6','7','8','9','10','J','Q','K'];
function validMove(card, foundation) {
  const ci = VALS.indexOf(card.value);
  const fi = VALS.indexOf(foundation.value);
  return (ci + 1) % 13 === fi || (fi + 1) % 13 === ci;
}
```

### Screens
1. PLAYING — full game
2. WIN — overlay, auto-advances after `win_screen_duration_ms`, any tap → CTA
3. FAIL — overlay, auto-advances after `fail_screen_duration_ms`, any tap → CTA
4. END — full-screen CTA, any tap → `mraid.open(target_url)`

### Multi-level flow
- A build contains 2–3 short levels played back to back
- When all tableau cards are cleared → quick win animation → next level loads
- Last level clears → END screen (CTA)
- Future: each level may have its own card design + background theme (NOT in V1)

### Per-level enter animation (defined in each level's JSON)
Two fields per level:
- `enter_animation`: one of the enum values below
- `enter_duration_ms`: total time from first card entering frame to all cards settled in place

| Value | Description |
|-------|-------------|
| `shuffle_in` (default) | Each card flies in from a random off-screen location, in order — lower rows first |
| `drop_down` | All cards fall from above into their positions |
| `bulk` | All cards move together as one unit into place |

These are an **enum** in the schema (not free-text strings) so the UI can offer a dropdown.

### UI requirement for config tool
- Any field that is an enum (like `enter_animation`, `card_move_speed`, `animation_type`) must be presented as a **dropdown/select** in the UI — never a text input
- Users should never need to remember or type string values

### Schema updates needed before building engine
- `schemas.py` — update `LevelLayout` for col/row format + `show_draw_pile` + `testing_mode` + `enter_animation` enum + `enter_duration_ms`
- `defaults/levels.json` — update to new schema

---

## Levels JSON format (new — not yet updated in files)

```json
{
  "levels_version": "1.0",
  "genre": "solitaire_simplified",
  "testing_mode": false,
  "total_levels": 3,
  "levels": [
    {
      "level_id": 1,
      "show_draw_pile": true,
      "layout": {
        "foundation_card": "7H",
        "tableau": [
          {"code": "6S", "face_up": true,  "col": 0, "row": 0},
          {"code": "8D", "face_up": true,  "col": 1, "row": 0},
          {"code": "6C", "face_up": true,  "col": 2, "row": 0},
          {"code": "3H", "face_up": false, "col": 0, "row": 1},
          {"code": "KS", "face_up": false, "col": 2, "row": 1}
        ],
        "draw_pile": ["AS", "2D", "QH", "5C", "9H"],
        "grid": {
          "cell_width": 76,
          "cell_height": 100,
          "origin_x": 0.5,
          "origin_y": 0.18
        }
      },
      "timings": {
        "win_screen_duration_ms": 2000,
        "fail_screen_duration_ms": 2000,
        "level_transition_duration_ms": 1000
      }
    }
  ]
}
```

---

## User Preferences (important for working style)

- **Go slow, explain every step** — especially anything the user needs to do themselves
- **Only ask product/design questions** — technical decisions can be made autonomously
- **Explain like to a child** whenever the user needs to do something manually
- **Don't ask before making technical calls** — just make them and explain after if needed
- User is a non-technical game designer — avoid jargon without explanation

---

## File Notes

- `PlayableIdea.txt` — original brief, good for high-level product vision. **Schemas and technical decisions in that file are outdated — use CLAUDE.md as the source of truth.**
- `CLAUDE.md` (this file) — live working document, always up to date. Supersedes PlayableIdea.txt on all technical details.
- `static/index.html` — placeholder only, will be replaced by engine files
- `runs/` — fills up as builds are generated, each subfolder is one build

---

## How to Keep This File Updated

At the end of every session or after any major decision:
1. Update the Milestone Status table
2. Add any new locked-in decisions to Key Decisions
3. Update the Engine Spec if anything changed
4. Note any unresolved questions or blockers at the bottom
