import json
import os
import random
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import anthropic as anthropic_sdk

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from randomizer import randomize_levels, randomize_mechanics, randomize_visual
from schemas import GridConfig, LevelLayout, LevelsConfig, MechanicsConfig, RunConfigs, SeedConfig, VisualConfig

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
DEFAULTS_DIR = BASE_DIR / "defaults"
RUNS_DIR = BASE_DIR / "runs"
STATIC_DIR = BASE_DIR / "static"

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Playable Ad Generator", version="1.0.0")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def startup():
    RUNS_DIR.mkdir(exist_ok=True)
    DEFAULTS_DIR.mkdir(exist_ok=True)
    STATIC_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


# ---------------------------------------------------------------------------
# Routes — static / health
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# ---------------------------------------------------------------------------
# GET /api/defaults
# ---------------------------------------------------------------------------

@app.get("/api/defaults")
async def get_defaults():
    """Return all three default config files."""
    try:
        return {
            "mechanics": _load_json(DEFAULTS_DIR / "mechanics.json"),
            "levels":    _load_json(DEFAULTS_DIR / "levels.json"),
            "visual":    _load_json(DEFAULTS_DIR / "visual.json"),
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Default config missing: {e.filename}")


# ---------------------------------------------------------------------------
# GET /api/runs
# ---------------------------------------------------------------------------

@app.get("/api/runs")
async def list_runs():
    """List all previous runs, most recent first."""
    runs = []
    for folder in sorted(RUNS_DIR.iterdir(), reverse=True):
        if not folder.is_dir():
            continue
        runs.append({
            "run_id":     folder.name,
            "created_at": datetime.fromtimestamp(folder.stat().st_mtime).isoformat(),
            "has_seed":   (folder / "seed.json").exists(),
            "has_build":  (folder / "index.html").exists(),
        })
    return runs


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}
# ---------------------------------------------------------------------------

@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    """Load configs from a specific previous run."""
    folder = _run_dir(run_id)
    if not folder.exists():
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    result = {}
    for section in ("mechanics", "levels", "visual"):
        config_file = folder / f"{section}.json"
        if config_file.exists():
            result[section] = _load_json(config_file)

    seed_file = folder / "seed.json"
    if seed_file.exists():
        result["seed"] = _load_json(seed_file)

    return result


# ---------------------------------------------------------------------------
# POST /api/randomize
# ---------------------------------------------------------------------------

class RandomizeRequest(BaseModel):
    section: Literal["mechanics", "levels", "visual"]
    config: dict
    variation: float = 0.3  # 0.0 = no change, 1.0 = maximum variation


@app.post("/api/randomize")
async def randomize(req: RandomizeRequest):
    """
    Randomize a single config section based on current values + variation amount.
    Returns the new config and the seed used (for reproducibility).
    """
    seed = random.randint(0, 2**31)

    try:
        if req.section == "mechanics":
            config = MechanicsConfig(**req.config)
            result = randomize_mechanics(config, req.variation, seed)

        elif req.section == "visual":
            config = VisualConfig(**req.config)
            result = randomize_visual(config, req.variation, seed)

        elif req.section == "levels":
            config = LevelsConfig(**req.config)
            result = randomize_levels(config, req.variation, seed)

    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid config for section '{req.section}': {e}")

    return {
        "section": req.section,
        "seed":    seed,
        "config":  result.dict(),
    }


# ---------------------------------------------------------------------------
# POST /api/generate  (stub — Claude integration added in M6)
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    mechanics: dict
    levels: dict
    visual: dict
    seed: Optional[dict] = None


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """
    Validate configs, create a run folder, save all configs, and produce a
    self-contained HTML playable ad by injecting the config into the engine template.
    """
    # Validate all three sections via Pydantic
    try:
        mechanics = MechanicsConfig(**req.mechanics)
        levels    = LevelsConfig(**req.levels)
        visual    = VisualConfig(**req.visual)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Config validation failed: {e}")

    # Create run folder
    run_id = f"build_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    folder = _run_dir(run_id)
    folder.mkdir(parents=True, exist_ok=True)

    # Save configs
    _save_json(folder / "mechanics.json", mechanics.dict())
    _save_json(folder / "levels.json",    levels.dict())
    _save_json(folder / "visual.json",    visual.dict())

    if req.seed:
        _save_json(folder / "seed.json", req.seed)

    # Build self-contained HTML by injecting the full config into the engine template
    template_path = STATIC_DIR / "engine_template.html"
    if not template_path.exists():
        raise HTTPException(status_code=500, detail="engine_template.html not found in static/")

    full_config = {
        "mechanics": mechanics.dict(),
        "levels":    levels.dict(),
        "visual":    visual.dict(),
    }
    config_json = json.dumps(full_config)

    template_html = template_path.read_text(encoding="utf-8")
    output_html   = template_html.replace("__GAME_CONFIG__", config_json)

    html_path = folder / "index.html"
    html_path.write_text(output_html, encoding="utf-8")

    return {
        "run_id":   run_id,
        "status":   "ready",
        "play_url": f"/runs/{run_id}/play",
    }


# ---------------------------------------------------------------------------
# POST /api/describe/gameplay — translate free-text description → LevelLayout
# ---------------------------------------------------------------------------

GAMEPLAY_SYSTEM_PROMPT = """You are a level designer for a simplified solitaire card game.

GAME RULES:
- The foundation is one face-up card. The player taps tableau cards to play onto it.
- A move is valid if the card value is exactly ±1 from the foundation value.
- Values wrap: King (K) and Ace (A) are adjacent (K→A and A→K are both valid).
- No suit matching — only value matters.
- Value order: A 2 3 4 5 6 7 8 9 10 J Q K (then back to A)
- After a tableau card is played, the next face-down card in that column flips face-up.
- Win = all tableau cards played. Lose = no valid moves and draw pile empty.

CARD CODES:
- Values: A 2 3 4 5 6 7 8 9 10 J Q K
- Suits: H (hearts) D (diamonds) C (clubs) S (spades)
- Examples: "7H", "10S", "AS", "KD"

LAYOUT FORMAT:
- col: column index, 0-based left to right
- row: 0 = the face-up card visible at the top of the column
- row 1, 2, ... = face-down cards stacked beneath, revealed top-to-bottom when the face-up card above is played
- face_up: true for row=0 cards, false for row>0 cards (unless specifically described otherwise)

YOUR JOB:
1. Read the description carefully.
2. Work out the full solve_sequence — the exact order cards must be played to clear the board. Verify every step is a valid ±1 move before proceeding.
3. Only then output the layout using the generate_level_layout tool.
4. Keep levels simple: 3–8 tableau cards total, at most 2 face-down rows per column.
5. Do NOT include grid sizing — that is computed automatically.
"""

GAMEPLAY_TOOL = {
    "name": "generate_level_layout",
    "description": "Output a solitaire level layout as structured data.",
    "input_schema": {
        "type": "object",
        "properties": {
            "foundation_card": {
                "type": "string",
                "description": "The starting face-up foundation card, e.g. '7H'"
            },
            "tableau": {
                "type": "array",
                "description": "All tableau cards with their positions",
                "items": {
                    "type": "object",
                    "properties": {
                        "code":    {"type": "string",  "description": "Card code e.g. '6S', '10D', 'AS'"},
                        "face_up": {"type": "boolean", "description": "true if visible, false if hidden"},
                        "col":     {"type": "integer", "description": "Column index, 0-based"},
                        "row":     {"type": "integer", "description": "Row index, 0 = top face-up card"}
                    },
                    "required": ["code", "face_up", "col", "row"]
                }
            },
            "draw_pile": {
                "type": "array",
                "description": "Cards in the draw pile (empty list if none)",
                "items": {"type": "string"}
            },
            "solve_sequence": {
                "type": "array",
                "description": "The exact order to play cards to win. Include foundation state at each step.",
                "items": {"type": "string"}
            }
        },
        "required": ["foundation_card", "tableau", "draw_pile", "solve_sequence"]
    }
}


class DescribeGameplayRequest(BaseModel):
    description: str
    level_index: int = 0


@app.post("/api/describe/gameplay")
async def describe_gameplay(req: DescribeGameplayRequest):
    """
    Translate a free-text level description into a validated LevelLayout
    using Claude. Returns the layout dict ready to populate the form.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured in .env")

    client = anthropic_sdk.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2048,
            system=GAMEPLAY_SYSTEM_PROMPT,
            tools=[GAMEPLAY_TOOL],
            tool_choice={"type": "any"},
            messages=[
                {"role": "user", "content": req.description}
            ]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude API error: {e}")

    # Extract tool use result
    tool_result = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "generate_level_layout":
            tool_result = block.input
            break

    if not tool_result:
        raise HTTPException(status_code=500, detail="AI did not return a layout. Try rephrasing your description.")

    # Auto-compute grid sizing from column count
    tableau = tool_result.get("tableau", [])
    if tableau:
        num_cols = max(card["col"] for card in tableau) + 1
        cell_width = max(56, min(90, int(360 // num_cols)))
    else:
        num_cols = 1
        cell_width = 82

    grid = GridConfig(cell_width=cell_width, cell_height=110, origin_x=0.5, origin_y=0.18)

    # Validate with Pydantic
    try:
        layout = LevelLayout(
            foundation_card=tool_result["foundation_card"],
            tableau=tableau,
            draw_pile=tool_result.get("draw_pile", []),
            grid=grid,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Layout validation failed: {e}")

    result = layout.dict()
    # Convert EnumValues/objects to plain dicts for JSON serialisation
    result["tableau"] = [
        {"code": c.code, "face_up": c.face_up, "col": c.col, "row": c.row}
        for c in layout.tableau
    ]
    result["grid"] = {
        "cell_width":  layout.grid.cell_width,
        "cell_height": layout.grid.cell_height,
        "origin_x":    layout.grid.origin_x,
        "origin_y":    layout.grid.origin_y,
    }

    return {"layout": result, "solve_sequence": tool_result.get("solve_sequence", [])}


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/play — serve the generated playable ad HTML
# ---------------------------------------------------------------------------

@app.get("/runs/{run_id}/play", include_in_schema=False)
async def play_run(run_id: str):
    html_file = _run_dir(run_id) / "index.html"
    if not html_file.exists():
        raise HTTPException(status_code=404, detail=f"No HTML build found for run '{run_id}'.")
    return FileResponse(html_file, media_type="text/html")
