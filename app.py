import json
import logging
import os
import random
import shutil
from datetime import datetime
from io import BytesIO
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
# Logging — writes to logs/server.log + console
# ---------------------------------------------------------------------------

LOG_DIR  = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "server.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("ad_gen")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR     = Path(__file__).parent
DEFAULTS_DIR = BASE_DIR / "defaults"
RUNS_DIR     = BASE_DIR / "runs"
STATIC_DIR   = BASE_DIR / "static"
ASSETS_DIR   = STATIC_DIR / "assets" / "project"
HISTORY_DIR  = STATIC_DIR / "assets" / "history"

# Asset slots — these are the swappable image files
ASSET_SLOTS = [
    {"name": "background",   "description": "Full background image",       "size": (390, 844)},
    {"name": "card_back",    "description": "Card back face (face-down)",  "size": (60,  84)},
    {"name": "felt",         "description": "Table surface / felt texture", "size": (366, 560)},
    {"name": "suit_spade",   "description": "Spade suit icon ♠",           "size": (100, 100)},
    {"name": "suit_heart",   "description": "Heart suit icon ♥",           "size": (100, 100)},
    {"name": "suit_diamond", "description": "Diamond suit icon ♦",         "size": (100, 100)},
    {"name": "suit_club",    "description": "Club suit icon ♣",            "size": (100, 100)},
]
ASSET_SLOT_NAMES = {s["name"] for s in ASSET_SLOTS}

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Playable Ad Generator", version="1.0.0")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _ensure_placeholder_assets():
    """
    Create solid-colour placeholder PNGs for any asset slot that has no file yet.
    Colours come from defaults/visual.json so placeholders match the current theme.
    """
    from PIL import Image as PILImage
    try:
        visual = _load_json(DEFAULTS_DIR / "visual.json")
    except Exception:
        visual = {}

    colour_map = {
        "background": visual.get("background_color", "#1a472a"),
        "card_back":  visual.get("card_back_color",  "#1a237e"),
        "felt":       visual.get("table_felt_color",  "#15803d"),
    }

    for slot in ASSET_SLOTS:
        dest = ASSETS_DIR / f"{slot['name']}.png"
        if dest.exists():
            continue
        hex_col = colour_map.get(slot["name"], "#333333").lstrip("#")
        r, g, b = int(hex_col[0:2], 16), int(hex_col[2:4], 16), int(hex_col[4:6], 16)
        img = PILImage.new("RGB", slot["size"], (r, g, b))
        img.save(dest, "PNG")
        log.info(f"Created placeholder asset: {dest.name}  {slot['size']}  #{hex_col}")


@app.on_event("startup")
async def startup():
    RUNS_DIR.mkdir(exist_ok=True)
    DEFAULTS_DIR.mkdir(exist_ok=True)
    STATIC_DIR.mkdir(exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_placeholder_assets()


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


class PendingRequest(BaseModel):
    category: str
    level_number: Optional[int] = None
    reasoning: str
    complexity: str


class BuildWithRequestsRequest(BaseModel):
    mechanics: dict
    levels: dict
    visual: dict
    pending_requests: list[PendingRequest]
    seed: Optional[dict] = None


@app.post("/api/build-with-requests")
async def build_with_requests(req: BuildWithRequestsRequest):
    """
    Smart build: Apply all pending requests using Claude, then generate the build.
    Claude reads all pending requests and returns updated configs.
    """
    log.info(f"POST /api/build-with-requests — {len(req.pending_requests)} pending requests")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured in .env")

    client = anthropic_sdk.Anthropic(api_key=api_key)

    # Build the prompt with all pending requests
    requests_text = "PENDING CHANGE REQUESTS:\n\n"
    for i, pr in enumerate(req.pending_requests, 1):
        category_labels = {
            "game_design": "🎮 Game Design (Global)",
            "level_design": f"🎯 Level Design (Level {pr.level_number})" if pr.level_number else "🎯 Level Design",
            "graphics_ui": "🎨 Graphics & UI (Global)",
            "animation": "✨ Animation & Polish (Global)",
            "legacy": "📝 Legacy"
        }
        category_label = category_labels.get(pr.category, pr.category)

        requests_text += f"{i}. {category_label}\n"
        requests_text += f"   Reasoning: {pr.reasoning}\n"
        requests_text += f"   Complexity: {pr.complexity}\n\n"

    # Add current configs
    current_configs = f"""
CURRENT CONFIGURATIONS:

=== MECHANICS.JSON ===
{json.dumps(req.mechanics, indent=2)}

=== LEVELS.JSON ===
{json.dumps(req.levels, indent=2)}

=== VISUAL.JSON ===
{json.dumps(req.visual, indent=2)}

{requests_text}

Apply all these changes and return the updated configurations using the update_game_configs tool.
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=8000,
            system=SMART_BUILD_SYSTEM,
            tools=[UPDATE_CONFIGS_TOOL],
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": current_configs}]
        )
    except Exception as e:
        log.error(f"Claude API error in build-with-requests: {e}")
        raise HTTPException(status_code=500, detail=f"Claude API error: {e}")

    # Extract tool result
    tool_result = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "update_game_configs":
            tool_result = block.input
            break

    if not tool_result:
        raise HTTPException(status_code=500, detail="AI did not return updated configs")

    # Validate configs
    try:
        updated_mechanics = MechanicsConfig(**tool_result["mechanics"])
        updated_levels = LevelsConfig(**tool_result["levels"])
        updated_visual = VisualConfig(**tool_result["visual"])
    except Exception as e:
        log.warning(f"Config validation failed: {e}")
        raise HTTPException(status_code=422, detail=f"Updated config validation failed: {e}")

    changes_summary = tool_result.get("changes_summary", "Changes applied")
    skipped = tool_result.get("skipped_requests", [])

    log.info(f"Smart build: {changes_summary}")
    if skipped:
        log.warning(f"Skipped requests: {skipped}")

    # Now proceed with normal build using updated configs
    run_id = f"build_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    folder = _run_dir(run_id)
    folder.mkdir(parents=True, exist_ok=True)

    # Save configs
    _save_json(folder / "mechanics.json", updated_mechanics.dict())
    _save_json(folder / "levels.json", updated_levels.dict())
    _save_json(folder / "visual.json", updated_visual.dict())

    if req.seed:
        _save_json(folder / "seed.json", req.seed)

    # Save a log of what was applied
    _save_json(folder / "applied_requests.json", {
        "requests": [pr.dict() for pr in req.pending_requests],
        "changes_summary": changes_summary,
        "skipped_requests": skipped
    })

    # Build self-contained HTML
    template_path = STATIC_DIR / "engine_template.html"
    if not template_path.exists():
        raise HTTPException(status_code=500, detail="engine_template.html not found in static/")

    # Embed assets
    import base64 as b64mod
    visual_dict = updated_visual.dict()
    assets_embedded = {}
    for slot in ASSET_SLOTS:
        png_path = ASSETS_DIR / f"{slot['name']}.png"
        if png_path.exists():
            b64 = b64mod.b64encode(png_path.read_bytes()).decode("utf-8")
            visual_dict[f"{slot['name']}_image"] = b64
            assets_embedded[slot["name"]] = png_path.name
            run_assets = folder / "assets"
            run_assets.mkdir(exist_ok=True)
            shutil.copy2(png_path, run_assets / f"{slot['name']}.png")

    if assets_embedded:
        log.info(f"Embedded project assets into build: {assets_embedded}")

    full_config = {
        "mechanics": updated_mechanics.dict(),
        "levels": updated_levels.dict(),
        "visual": visual_dict,
    }
    config_json = json.dumps(full_config)

    template_html = template_path.read_text(encoding="utf-8")
    output_html = template_html.replace("__GAME_CONFIG__", config_json)

    html_path = folder / "index.html"
    html_path.write_text(output_html, encoding="utf-8")

    log.info(f"Smart build complete → {run_id}")

    return {
        "run_id": run_id,
        "status": "ready",
        "play_url": f"/runs/{run_id}/play",
        "changes_summary": changes_summary,
        "skipped_requests": skipped
    }


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """
    Validate configs, create a run folder, save all configs, and produce a
    self-contained HTML playable ad by injecting the config into the engine template.
    """
    log.info("POST /api/generate — validating configs")
    # Validate all three sections via Pydantic
    try:
        mechanics = MechanicsConfig(**req.mechanics)
        levels    = LevelsConfig(**req.levels)
        visual    = VisualConfig(**req.visual)
    except Exception as e:
        log.warning(f"Config validation failed: {e}")
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

    # Read project asset files and embed as base64 (overrides any values already in visual config)
    import base64 as b64mod
    visual_dict = visual.dict()
    assets_embedded = {}
    for slot in ASSET_SLOTS:
        png_path = ASSETS_DIR / f"{slot['name']}.png"
        if png_path.exists():
            b64 = b64mod.b64encode(png_path.read_bytes()).decode("utf-8")
            visual_dict[f"{slot['name']}_image"] = b64
            assets_embedded[slot["name"]] = png_path.name
            # Also save a copy in the run's assets folder for reference
            run_assets = folder / "assets"
            run_assets.mkdir(exist_ok=True)
            shutil.copy2(png_path, run_assets / f"{slot['name']}.png")

    if assets_embedded:
        log.info(f"Embedded project assets into build: {assets_embedded}")

    full_config = {
        "mechanics": mechanics.dict(),
        "levels":    levels.dict(),
        "visual":    visual_dict,
    }
    config_json = json.dumps(full_config)

    template_html = template_path.read_text(encoding="utf-8")
    output_html   = template_html.replace("__GAME_CONFIG__", config_json)

    html_path = folder / "index.html"
    html_path.write_text(output_html, encoding="utf-8")

    has_bg    = bool(visual.background_image)
    has_cb    = bool(visual.card_back_image)
    has_felt  = bool(visual.felt_image)
    log.info(f"Build complete → {run_id}  (bg_image={has_bg}, card_back_image={has_cb}, felt_image={has_felt})")

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

SMART_BUILD_SYSTEM = """You are a game configuration expert for a simplified solitaire card game.

You receive:
1. Current game configuration (mechanics, levels, visual settings)
2. List of pending change requests from the operator

Your job is to implement ALL requested changes and return updated configurations.

GAME STRUCTURE:
- mechanics.json: Core game rules (wrapping, suit matching, timing, etc.)
- levels.json: Array of level objects, each with foundation_card, tableau, draw_pile, grid
- visual.json: Visual styling (colors, fonts, card appearance, backgrounds)

CHANGE CATEGORIES:
- 🎮 Game Design (Global): Modify mechanics.json (e.g., disable wrapping, add timer)
- 🎯 Level Design: Modify specific level in levels.json array (use level_number to find it)
- 🎨 Graphics & UI (Global): Modify visual.json (colors, fonts, card styling)
- ✨ Animation & Polish (Global): Modify visual.json (animation timings, effects)
- 📝 Legacy: Can modify any config

IMPORTANT RULES:
1. Read ALL pending requests carefully before making ANY changes
2. Apply changes in order: Game Design → Level Design → Graphics → Animation
3. For Level Design: Find the level by index (level_number - 1 in the array)
4. Validate all changes maintain game solvability and consistency
5. If a request conflicts or is impossible, note it but continue with other changes
6. Return COMPLETE configs (don't omit unchanged fields)

Use the update_game_configs tool to return all three updated configuration objects.
"""

APPLY_CONFIG_CHANGES_TOOL = {
    "name": "apply_config_changes",
    "description": "Return the updated configuration section after applying the requested changes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "config_section": {
                "type": "string",
                "description": "Which config to update: 'mechanics', 'visual', or 'levels'",
                "enum": ["mechanics", "visual", "levels"]
            },
            "updated_config": {
                "type": "object",
                "description": "The complete updated configuration object with your changes applied"
            },
            "changes_summary": {
                "type": "string",
                "description": "Brief 1-2 sentence summary of what you changed"
            }
        },
        "required": ["config_section", "updated_config", "changes_summary"]
    }
}

UPDATE_CONFIGS_TOOL = {
    "name": "update_game_configs",
    "description": "Return the updated game configuration objects after applying all pending requests.",
    "input_schema": {
        "type": "object",
        "properties": {
            "mechanics": {
                "type": "object",
                "description": "Complete mechanics configuration object"
            },
            "levels": {
                "type": "object",
                "description": "Complete levels configuration object with 'levels' array"
            },
            "visual": {
                "type": "object",
                "description": "Complete visual configuration object"
            },
            "changes_summary": {
                "type": "string",
                "description": "Brief summary of what changes were applied"
            },
            "skipped_requests": {
                "type": "array",
                "description": "List of requests that couldn't be applied (with reasons)",
                "items": {"type": "string"}
            }
        },
        "required": ["mechanics", "levels", "visual", "changes_summary"]
    }
}

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
# Visual Editor endpoints
# ---------------------------------------------------------------------------

class EnhancePromptRequest(BaseModel):
    rough_prompt: str
    screenshot: str  # base64


class GenerateImagesRequest(BaseModel):
    prompt: str
    reference_image: Optional[str] = None  # base64
    num_variations: int = 2


class VisualLayoutRequest(BaseModel):
    screenshot: Optional[str] = None       # base64 — current build state (optional for text-only requests)
    annotations: Optional[str] = None     # base64 — drawing layer (legacy separate field)
    nanobanana_reference: Optional[str] = None  # base64 — Nanobanana output
    reference_images: Optional[list[str]] = None  # base64 list — @ImageXX referenced images
    text_note: Optional[str] = None
    has_drawing: bool = False              # True when screenshot contains user-drawn marks baked in
    level_index: Optional[int] = None      # from dropdown or auto-detected (None = auto-detect)
    game_metadata: Optional[dict] = None   # game state metadata (level number, foundation, etc.)
    category: str = "legacy"               # game_design, level_design, graphics_ui, animation, legacy


class ReplaceAssetsRequest(BaseModel):
    asset_names: list[str]               # e.g. ["background", "card_back"]
    reference_image: str                 # base64 — target style reference
    annotations: Optional[str] = None   # base64 — drawing on reference


class AssetEditPreviewRequest(BaseModel):
    asset_name: str     # e.g. "background"
    prompt: str         # user's description of the desired change
    reference_images: Optional[list[str]] = None  # @ImageXX references from the library


class AssetApproveRequest(BaseModel):
    asset_name: str     # e.g. "background"
    image_b64: str      # base64 PNG of the approved result


# (ASSET_SLOTS defined at module level above)


@app.post("/api/nanobanana/enhance-prompt")
async def enhance_prompt_endpoint(req: EnhancePromptRequest):
    """
    Claude Vision suggests 3 refined image-generation prompts based on
    the operator's rough description and a screenshot of the current build.
    """
    log.info(f"POST /api/nanobanana/enhance-prompt — rough_prompt={repr(req.rough_prompt[:80])}")
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured in .env")
    try:
        from gemini import enhance_prompt
        suggestions = enhance_prompt(req.rough_prompt, req.screenshot)
        log.info(f"enhance-prompt OK — {len(suggestions)} suggestions returned")
        return {"suggestions": suggestions}
    except Exception as e:
        log.error(f"enhance-prompt failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/nanobanana/generate")
async def generate_images_endpoint(req: GenerateImagesRequest):
    """
    Call Gemini image generation.
    Image-to-image if reference_image provided, text-to-image otherwise.
    Returns list of base64-encoded PNG strings.
    """
    mode = "image-to-image" if req.reference_image else "text-to-image"
    log.info(f"POST /api/nanobanana/generate — mode={mode}, prompt={repr(req.prompt[:80])}, n={req.num_variations}")
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured in .env")
    try:
        from gemini import generate_images
        images = generate_images(req.prompt, req.reference_image, req.num_variations)
        log.info(f"nanobanana/generate OK — {len(images)} images returned")
        return {"images": images}
    except Exception as e:
        log.error(f"nanobanana/generate failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


VISUAL_LAYOUT_SYSTEM = """You are a level designer for a simplified solitaire card game.

You receive a screenshot of the current build and optional instructions.

== READING DRAWN ANNOTATIONS ==
When the image contains operator-drawn marks (colored lines, arrows, shapes), treat them as
layout instructions — they ARE the change request. Read them carefully before deciding anything:

  → Arrow          = move the thing at the tail to where the arrow points
  □ Box / rectangle = resize, regroup, or restructure the enclosed area
  ✕ or X mark      = remove this card / column
  + or circle      = add something here
  Line between A→B = create a relationship or path from A to B
  Number or label  = set this column/row to that count

Read the ENTIRE image systematically: scan each mark, understand its spatial position
relative to the cards and columns, then translate all marks together into a coherent
layout change. If an arrow points from a card to an empty space, that card moves there.
If a box encloses 2 columns, those columns should be grouped or resized together.

== CARD CODES ==
Values: A 2 3 4 5 6 7 8 9 10 J Q K + suits H D C S. Examples: "7H", "10S", "AS".

== GRID COORDINATES ==
col=0 is leftmost column. row=0 is the top face-up card. Higher rows are face-down beneath it.
Do NOT include a grid field — the server computes it automatically.

== OUTPUT ==
Use the generate_level_layout tool. Always verify the layout is solvable before outputting.
"""

# Category-specific system prompts for multi-category Path A
GAME_DESIGN_SYSTEM = """You are an EXPERIENCED game designer specializing in casual card games.

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

WHEN WRITING YOUR REASONING (before using the tool):
1. Start with "I understand you want to [intent]. Setting [field] to [value]."
2. **ONLY warn if there's a CRITICAL BREAKING ISSUE**:
   - ⚠️ Will make existing levels UNSOLVABLE → WARN: "This will break all current levels because [reason]"
   - ⚠️ Creates game-breaking exploits → WARN: "This allows players to [exploit]"
   - ⚠️ Fundamentally changes core loop → WARN: "This completely changes the game from [A] to [B]"
3. **DON'T warn about difficulty/balance opinions** - trust the operator knows what they want
4. Be brief - only critical breaking issues deserve warnings

THEN use the apply_config_changes tool:
1. Read the CURRENT MECHANICS CONFIG provided
2. Modify the config object to implement the changes
3. Return:
   - config_section: "mechanics"
   - updated_config: the complete mechanics object with your changes
   - changes_summary: brief explanation of what you changed

IMPORTANT: Return the COMPLETE config object with your modifications, not just the changed fields.
"""

LEVEL_DESIGN_SYSTEM = """You are a level designer for a simplified solitaire card game.

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
"""

GRAPHICS_UI_SYSTEM = """You are an EXPERIENCED technical artist for a mobile card game playable ad.

VISUAL CONFIG STRUCTURE:
- Colors: background_color, card_back_color, table_felt_color, card_border_color, foundation_border_color
- Text: font_family, font_color, title_font_size
- Card dimensions: card_width (default 70), card_height (default 96) - change these to resize all cards globally
- Card styling: card_border_width, card_corner_radius, card_shadow (with enabled, offset_x, offset_y, blur_radius, color, spread)
- Images: background_image, card_back_image, felt_image (base64 PNG data)
- Suit icons: suit_spade_image, suit_heart_image, suit_diamond_image, suit_club_image (base64 PNG data)

IMPORTANT TECHNICAL CONSTRAINTS:
- Suit icons are FIXED SIZE (rendered at specific coordinates on cards) - they DON'T auto-scale with card size
- Card value text is FIXED SIZE - doesn't scale with card dimensions
- Pip positions for number cards are HARDCODED - won't adjust if card size changes

YOUR TASK:
The operator wants to modify VISUAL/UI elements that affect the ENTIRE game.

WHEN WRITING YOUR REASONING (before using the tool):
1. Start with "I understand you want to [intent]. Setting [field] to [value]."
2. **ONLY warn if there's a CRITICAL TECHNICAL ISSUE** that will cause rendering bugs or breakage:
   - ⚠️ Card size changes → WARN: "This will cause suit icons and text to overflow/underflow since they don't auto-scale"
   - ⚠️ Breaking changes → WARN: "This will break [specific thing]"
   - ⚠️ Rendering bugs → WARN: "This creates a rendering issue where [problem]"
3. **DON'T warn about obvious design choices** (colors, fonts, simple styling) - the operator knows what they want
4. Be brief - only add warnings when absolutely necessary

THEN use the apply_config_changes tool:
1. Read the CURRENT VISUAL CONFIG provided
2. Modify the config object to implement the changes (add new fields if needed)
3. Return:
   - config_section: "visual"
   - updated_config: the complete visual object with your changes
   - changes_summary: brief explanation of what you changed

IMPORTANT: Return the COMPLETE config object with your modifications, not just the changed fields.
"""

ANIMATION_SYSTEM = """You are an EXPERIENCED technical animator specializing in mobile game performance.

ANIMATION CONFIG STRUCTURE (stored in visual config):
- Card flip speed, slide timing, bounce effects
- Particle systems (sparkles, confetti, etc.)
- Transition easing functions
- Visual feedback (tap ripple, success animations)
- Animation timing: card_flip_duration, slide_duration, etc.

YOUR TASK:
The operator wants to add or modify ANIMATION/MOTION that affects the ENTIRE game.

WHEN WRITING YOUR REASONING (before using the tool):
1. Start with "I understand you want to [intent]. Setting [field] to [value]."
2. **ONLY warn if there's a CRITICAL PERFORMANCE/TECHNICAL ISSUE**:
   - ⚠️ Severe performance impact → WARN: "Particle count over 100 will cause severe lag on low-end devices"
   - ⚠️ Animation conflicts → WARN: "This timing conflicts with [existing animation] causing visual glitches"
   - ⚠️ Breaking changes → WARN: "This will break [specific thing]"
3. **DON'T warn about subjective feel/pacing** - trust the operator's judgment
4. Be brief - only critical technical issues deserve warnings

THEN use the apply_config_changes tool:
1. Read the CURRENT VISUAL CONFIG provided (animations are stored here)
2. Modify the config object to add/update animation properties
3. Return:
   - config_section: "visual"
   - updated_config: the complete visual object with your animation changes
   - changes_summary: brief explanation of what you changed

IMPORTANT: Return the COMPLETE config object with your modifications, not just the changed fields.
"""

CATEGORY_PROMPTS = {
    "game_design": GAME_DESIGN_SYSTEM,
    "level_design": LEVEL_DESIGN_SYSTEM,
    "graphics_ui": GRAPHICS_UI_SYSTEM,
    "animation": ANIMATION_SYSTEM,
    "legacy": VISUAL_LAYOUT_SYSTEM,
}


def detect_level_number(
    category: str,
    level_index: Optional[int],
    game_metadata: Optional[dict],
    text_note: Optional[str]
) -> Optional[int]:
    """
    Detect which level number is being modified using priority system:
    1. Explicit user selection (dropdown)
    2. Game metadata (from Capture button)
    3. Text parsing (search for "level 3", "lv2", etc.)
    4. Default to None (will use 1 as fallback in prompt)
    """
    # Priority 1: Explicit selection
    if level_index is not None and level_index >= 0:
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

    # Priority 4: Return None (caller will use default)
    return None


@app.post("/api/visual/layout")
async def visual_layout(req: VisualLayoutRequest):  # noqa: F811
    """
    Path A endpoint: Claude Vision reads screenshot + optional annotations/reference/text
    and returns an updated LevelLayout reflecting the requested positional changes.
    Supports multi-category system with category-specific prompting.
    """
    # Detect level number for Level Design category
    level_number = None
    if req.category == "level_design":
        level_number = detect_level_number(
            req.category,
            req.level_index,
            req.game_metadata,
            req.text_note
        )
        if level_number is None:
            level_number = 1  # Default fallback

    has_ann = bool(req.annotations)
    has_ref = bool(req.nanobanana_reference)
    num_ref_images = len(req.reference_images) if req.reference_images else 0
    log.info(f"POST /api/visual/layout — category={req.category}, level={level_number}, has_drawing={req.has_drawing}, annotations={has_ann}, nanobanana_ref={has_ref}, ref_images={num_ref_images}, note={repr((req.text_note or '')[:60])}")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured in .env")

    client = anthropic_sdk.Anthropic(api_key=api_key)

    # Select system prompt based on category
    system_prompt = CATEGORY_PROMPTS.get(req.category, CATEGORY_PROMPTS["legacy"])

    # Inject level number into prompt if applicable
    if level_number is not None:
        system_prompt = system_prompt.replace("{level_number}", str(level_number))

    # Build the message content — always include screenshot, optionally others
    content = []

    def _add_image(b64: str, label: str):
        data = b64.split(",", 1)[1] if "," in b64 else b64
        content.append({"type": "text", "text": label})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": data}
        })

    # Add screenshot if provided
    if req.screenshot:
        # Label the screenshot — if it has drawings baked in, tell Claude explicitly
        if req.has_drawing:
            screenshot_label = (
                "Current build screenshot WITH operator-drawn annotations baked in.\n"
                "The colored marks drawn on this image are layout change instructions.\n"
                "Carefully identify every mark (arrows, boxes, lines, X, circles) and their\n"
                "positions relative to the cards and columns before generating the new layout."
            )
        else:
            screenshot_label = "Current build screenshot (no annotations):"

        _add_image(req.screenshot, screenshot_label)

    if req.nanobanana_reference:
        _add_image(req.nanobanana_reference, "Target reference image (what the operator wants it to look like):")

    if req.annotations:
        _add_image(req.annotations, "Drawing annotations (operator drew on top of the screenshot/reference):")

    # Add @ImageXX referenced images
    if req.reference_images:
        for idx, ref_img in enumerate(req.reference_images, 1):
            _add_image(ref_img, f"Reference Image {idx:02d} (@Image{idx:02d} referenced in text):")

    if req.has_drawing and not req.text_note:
        instruction = (
            "Read all drawn marks on the screenshot and translate them into layout changes. "
            "Describe each mark you see and what layout change it implies, then output the new layout."
        )
    else:
        instruction = req.text_note or "Update the layout to match the reference/annotations."

    # Add game state context if available
    context_text = f"Operator instruction: {instruction}"
    if req.game_metadata:
        meta = req.game_metadata
        context_parts = []
        if meta.get("level_number") is not None:
            context_parts.append(f"Level: {meta['level_number']}")
        if meta.get("foundation_card"):
            context_parts.append(f"Foundation: {meta['foundation_card']}")
        if meta.get("tableau_count"):
            context_parts.append(f"Tableau cards: {meta['tableau_count']}")
        if meta.get("draw_pile_count"):
            context_parts.append(f"Draw pile: {meta['draw_pile_count']}")

        if context_parts:
            context_text = f"Game state context: {', '.join(context_parts)}\n\n" + context_text

    # Final instruction based on category
    if req.category in ("level_design", "legacy"):
        content.append({"type": "text", "text": f"{context_text}\nUse the generate_level_layout tool to return the updated layout."})
    else:
        content.append({"type": "text", "text": f"{context_text}"})

    # Load current configs for non-layout categories
    current_configs = {}
    if req.category in ("game_design", "graphics_ui", "animation"):
        try:
            current_configs["mechanics"] = _load_json(DEFAULTS_DIR / "mechanics.json")
            current_configs["visual"] = _load_json(DEFAULTS_DIR / "visual.json")
        except Exception as e:
            log.warning(f"Could not load current configs: {e}")
            current_configs = {"mechanics": {}, "visual": {}}

    # Decide tool usage based on category
    # Build API call parameters conditionally
    api_params = {
        "model": "claude-sonnet-4-5-20250929",
        "max_tokens": 2048,
        "system": system_prompt + "\n\nIMPORTANT: Write 1-2 sentences in simple language explaining what you understand from the request and what changes you're making.",
        "messages": [{"role": "user", "content": content}]
    }

    # Add tools based on category
    if req.category in ("level_design", "legacy"):
        api_params["tools"] = [GAMEPLAY_TOOL]
        api_params["tool_choice"] = {"type": "auto"}
    elif req.category in ("game_design", "graphics_ui", "animation"):
        # Add config update tool and current config context
        api_params["tools"] = [APPLY_CONFIG_CHANGES_TOOL]
        api_params["tool_choice"] = {"type": "auto"}

        # Add current config to the message so Claude knows what to modify
        config_section = "mechanics" if req.category == "game_design" else "visual"
        current_config = current_configs.get(config_section, {})
        config_context = f"\n\nCURRENT {config_section.upper()} CONFIG:\n```json\n{json.dumps(current_config, indent=2)}\n```\n\nUse the apply_config_changes tool to return the updated config with your changes."
        api_params["messages"][0]["content"].append({"type": "text", "text": config_context})

    # Log what we're sending to Claude
    log.info("=" * 80)
    log.info(f"CLAUDE REQUEST - Category: {req.category}")
    log.info(f"Has screenshot: {req.screenshot is not None}")
    log.info(f"Has metadata: {req.game_metadata is not None}")
    if req.game_metadata:
        log.info(f"Metadata: {req.game_metadata}")
    log.info(f"User text: {req.text_note}")
    log.info(f"System prompt preview: {system_prompt[:200]}...")
    log.info("=" * 80)

    try:
        response = client.messages.create(**api_params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude API error: {e}")

    # Log Claude's full response
    log.info("=" * 80)
    log.info("CLAUDE RESPONSE:")
    log.info(f"Model: {response.model}, Stop reason: {response.stop_reason}")

    # Extract text reasoning and tool result from Claude's response
    tool_result = None
    config_changes = None
    reasoning_text = ""

    for block in response.content:
        if block.type == "text":
            reasoning_text += block.text + " "
            log.info(f"TEXT BLOCK: {block.text}")
        elif block.type == "tool_use":
            if block.name == "generate_level_layout":
                tool_result = block.input
                log.info(f"TOOL USE: generate_level_layout - foundation={block.input.get('foundation_card')}, tableau={len(block.input.get('tableau', []))} cards")
            elif block.name == "apply_config_changes":
                config_changes = block.input
                log.info(f"TOOL USE: apply_config_changes - section={block.input.get('config_section')}")

    log.info(f"Final reasoning text: {reasoning_text.strip()}")
    log.info("=" * 80)

    # For non-layout categories (game_design, graphics_ui, animation), expect config changes
    if req.category in ("game_design", "graphics_ui", "animation"):
        if not config_changes:
            raise HTTPException(status_code=500, detail="AI did not return config changes. Try adding more detail to your request.")

        result_payload = {
            "layout": None,
            "solve_sequence": [],
            "config_changes": {
                "section": config_changes.get("config_section"),
                "updated_config": config_changes.get("updated_config"),
                "summary": config_changes.get("changes_summary", "")
            },
            "reasoning": {
                "simple": reasoning_text.strip() or config_changes.get("changes_summary", "Config updated"),
                "complexity": "n/a"
            },
            "category": req.category,
            "level_number": level_number,
        }
        log.info(f"Config changes OK — category={req.category}, section={config_changes.get('config_section')}")
        return result_payload

    # For level_design and legacy, expect tool result
    if not tool_result:
        raise HTTPException(status_code=500, detail="AI did not return a layout. Try adding more detail.")

    # Assess complexity based on the layout changes
    tableau = tool_result.get("tableau", [])
    num_cards = len(tableau)
    num_cols = max((c["col"] for c in tableau), default=0) + 1
    draw_pile_count = len(tool_result.get("draw_pile", []))
    foundation = tool_result.get("foundation_card", "unknown")

    # Generate simple reasoning - use Claude's text or create descriptive fallback
    if reasoning_text.strip():
        reasoning_simple = reasoning_text.strip()
    else:
        # Create better fallback based on actual layout
        reasoning_simple = f"I've created a layout with foundation {foundation}, {num_cards} tableau cards arranged in {num_cols} column{'s' if num_cols != 1 else ''}"
        if draw_pile_count > 0:
            reasoning_simple += f", and {draw_pile_count} card{'s' if draw_pile_count != 1 else ''} in the draw pile"
        reasoning_simple += "."

    # Simple heuristic for complexity
    if num_cards <= 5 and num_cols <= 3 and draw_pile_count <= 3:
        complexity = "easy"
    elif num_cards >= 10 or num_cols >= 6 or draw_pile_count >= 8:
        complexity = "risky"
    else:
        complexity = "moderate"

    num_cols = max((c["col"] for c in tableau), default=0) + 1
    cell_width = max(56, min(90, int(360 // num_cols)))
    grid = GridConfig(cell_width=cell_width, cell_height=110, origin_x=0.5, origin_y=0.18)

    try:
        layout = LevelLayout(
            foundation_card=tool_result["foundation_card"],
            tableau=tableau,
            draw_pile=tool_result.get("draw_pile", []),
            grid=grid,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Layout validation failed: {e}")

    result_payload = {
        "layout": {
            "foundation_card": layout.foundation_card,
            "tableau": [{"code": c.code, "face_up": c.face_up, "col": c.col, "row": c.row} for c in layout.tableau],
            "draw_pile": list(layout.draw_pile),
            "grid": {"cell_width": layout.grid.cell_width, "cell_height": layout.grid.cell_height,
                     "origin_x": layout.grid.origin_x, "origin_y": layout.grid.origin_y},
        },
        "solve_sequence": tool_result.get("solve_sequence", []),
        "reasoning": {
            "simple": reasoning_simple,
            "complexity": complexity
        },
        "category": req.category,
        "level_number": level_number,
    }
    log.info(f"visual/layout OK — category={req.category}, level={level_number}, foundation={layout.foundation_card}, {len(layout.tableau)} tableau cards")
    return result_payload


# ── VISUAL EDITOR — Image Persistence ─────────────────────────────────────
REFERENCES_DIR = STATIC_DIR / "assets" / "references"
REFERENCES_DIR.mkdir(parents=True, exist_ok=True)


class SaveImageRequest(BaseModel):
    image_data: str  # base64 data URL
    image_number: int  # The global counter number (1, 2, 3, etc.)


@app.post("/api/visual/save-image")
async def save_reference_image(req: SaveImageRequest):
    """
    Save a reference image to disk at static/assets/references/image_XXX.png
    """
    import base64

    try:
        # Extract base64 data (strip data URL prefix if present)
        image_data = req.image_data
        if "," in image_data:
            image_data = image_data.split(",", 1)[1]

        # Decode base64
        image_bytes = base64.b64decode(image_data)

        # Save to disk with zero-padded number
        filename = f"image_{str(req.image_number).zfill(3)}.png"
        filepath = REFERENCES_DIR / filename

        with open(filepath, "wb") as f:
            f.write(image_bytes)

        log.info(f"Saved reference image: {filename}")

        return {
            "success": True,
            "filename": filename,
            "path": f"/static/assets/references/{filename}"
        }

    except Exception as e:
        log.error(f"Error saving reference image: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/visual/list-images")
async def list_reference_images():
    """
    List all saved reference images in static/assets/references/
    Returns array of {number, filename, url}
    """
    try:
        images = []

        # Scan the references directory
        if REFERENCES_DIR.exists():
            for filepath in sorted(REFERENCES_DIR.glob("image_*.png")):
                # Extract number from filename (image_001.png -> 1)
                try:
                    num_str = filepath.stem.split("_")[1]
                    number = int(num_str)
                    images.append({
                        "number": number,
                        "filename": filepath.name,
                        "url": f"/static/assets/references/{filepath.name}"
                    })
                except (IndexError, ValueError):
                    continue

        log.info(f"Listed {len(images)} reference images")
        return {"images": images}

    except Exception as e:
        log.error(f"Error listing reference images: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/visual/delete-image")
async def delete_reference_image(req: dict):
    """
    Delete a reference image from disk
    """
    try:
        image_number = req.get("image_number")
        if image_number is None:
            raise HTTPException(status_code=400, detail="image_number required")

        filename = f"image_{str(image_number).zfill(3)}.png"
        filepath = REFERENCES_DIR / filename

        if filepath.exists():
            filepath.unlink()
            log.info(f"Deleted reference image: {filename}")
            return {"success": True, "deleted": filename}
        else:
            return {"success": False, "error": "File not found"}

    except Exception as e:
        log.error(f"Error deleting reference image: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/visual/clear-all-images")
async def clear_all_reference_images():
    """
    Delete all reference images from disk
    """
    try:
        deleted_count = 0

        if REFERENCES_DIR.exists():
            for filepath in REFERENCES_DIR.glob("image_*.png"):
                filepath.unlink()
                deleted_count += 1

        log.info(f"Cleared all reference images ({deleted_count} files)")
        return {"success": True, "deleted_count": deleted_count}

    except Exception as e:
        log.error(f"Error clearing reference images: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/assets/list")
async def list_assets():
    """
    Return the project asset slots with current file thumbnails as base64.
    Reads from static/assets/project/{name}.png.
    """
    import base64
    assets = []
    for slot in ASSET_SLOTS:
        png = ASSETS_DIR / f"{slot['name']}.png"
        preview = None
        if png.exists():
            preview = base64.b64encode(png.read_bytes()).decode("utf-8")
        assets.append({
            "name":        slot["name"],
            "description": slot["description"],
            "file_path":   f"/static/assets/project/{slot['name']}.png",
            "has_file":    png.exists(),
            "preview":     preview,
        })
    log.info(f"assets/list — returning {len(assets)} slots")
    return {"assets": assets}


@app.get("/api/logs")
async def get_logs(n: int = 100):
    """Return the last n lines of the server log file."""
    if not LOG_FILE.exists():
        return {"lines": []}
    lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    return {"lines": lines[-n:]}


@app.post("/api/assets/replace")
async def replace_assets(req: ReplaceAssetsRequest):
    """
    Path B endpoint: generate new versions of selected assets using Gemini.
    Reads current PNG from static/assets/project/, backs up old to history/,
    saves new PNG, and returns updated base64 values.
    """
    import base64 as b64mod
    log.info(f"POST /api/assets/replace — assets={req.asset_names}, has_annotations={bool(req.annotations)}")

    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured in .env")

    for name in req.asset_names:
        if name not in ASSET_SLOT_NAMES:
            raise HTTPException(status_code=400, detail=f"Unknown asset '{name}'. Valid: {sorted(ASSET_SLOT_NAMES)}")

    from gemini import generate_asset
    from PIL import Image as PILImage

    updated = {}
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    for name in req.asset_names:
        png_path = ASSETS_DIR / f"{name}.png"

        # Read exact pixel dimensions from the current project file
        if png_path.exists():
            with PILImage.open(png_path) as im:
                width, height = im.size
        else:
            # Fall back to slot defaults if file not found
            slot = next((s for s in ASSET_SLOTS if s["name"] == name), None)
            width, height = slot["size"] if slot else (390, 844)

        log.info(f"Generating asset '{name}' at {width}x{height}px from reference")

        try:
            new_b64 = generate_asset(name, width, height, req.reference_image, req.annotations)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Asset generation failed for '{name}': {e}")

        # Back up old file before overwriting
        if png_path.exists():
            backup = HISTORY_DIR / f"{name}_{ts}.png"
            shutil.copy2(png_path, backup)
            log.info(f"Backed up {name}.png → history/{backup.name}")

        # Write new file
        png_path.write_bytes(b64mod.b64decode(new_b64))
        log.info(f"Saved new project asset: {png_path.name}  {width}x{height}px")
        updated[name] = new_b64

    log.info(f"assets/replace OK — saved: {list(updated.keys())}")
    return {"updated_assets": updated}


# ---------------------------------------------------------------------------
# POST /api/assets/edit-preview  — image-to-image edit, preview only (no save)
# ---------------------------------------------------------------------------

@app.post("/api/assets/edit-preview")
async def asset_edit_preview(req: AssetEditPreviewRequest):
    """
    Path C: generate a new version of one asset using image-to-image with the
    user's custom prompt.  Returns base64 PNG but does NOT save to disk.
    """
    if req.asset_name not in ASSET_SLOT_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown asset '{req.asset_name}'. Valid: {sorted(ASSET_SLOT_NAMES)}")
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured in .env")

    png_path = ASSETS_DIR / f"{req.asset_name}.png"
    if not png_path.exists():
        raise HTTPException(status_code=404, detail=f"Asset '{req.asset_name}' not found on disk")

    import base64 as b64mod
    from PIL import Image as PILImage

    ref_b64 = b64mod.b64encode(png_path.read_bytes()).decode()

    # Get original dimensions so we can resize the output to match exactly
    with PILImage.open(png_path) as _im:
        orig_w, orig_h = _im.size

    from gemini import generate_images
    log.info(f"POST /api/assets/edit-preview — asset={req.asset_name}, prompt={req.prompt[:80]!r}")

    # Process additional reference images (@ImageXX references)
    additional_refs = None
    if req.reference_images:
        additional_refs = []
        for img_data in req.reference_images:
            # Strip data URL prefix if present
            if img_data.startswith('data:image'):
                img_data = img_data.split(',', 1)[1]
            additional_refs.append(img_data)
        log.info(f"  Including {len(additional_refs)} additional reference images")

    try:
        # Only pass additional_reference_images if we have any
        if additional_refs:
            results = generate_images(
                req.prompt,
                reference_image_b64=ref_b64,
                num_variations=1,
                additional_reference_images=additional_refs
            )
        else:
            # No additional images, use original API call
            results = generate_images(
                req.prompt,
                reference_image_b64=ref_b64,
                num_variations=1
            )
    except Exception as e:
        log.error(f"Gemini API error: {e}")
        raise HTTPException(status_code=500, detail=f"Gemini API error: {str(e)}")

    if not results:
        raise HTTPException(status_code=500, detail="Gemini did not return an image")

    # Resize output to exactly match the original asset dimensions
    raw_bytes = b64mod.b64decode(results[0])
    out_img = PILImage.open(BytesIO(raw_bytes)).convert("RGBA")
    if out_img.size != (orig_w, orig_h):
        log.info(f"  Resizing from {out_img.size} -> ({orig_w}, {orig_h})")
        out_img = out_img.resize((orig_w, orig_h), PILImage.LANCZOS)
    buf = BytesIO()
    out_img.save(buf, "PNG")
    result_b64 = b64mod.b64encode(buf.getvalue()).decode()

    log.info(f"assets/edit-preview OK — asset={req.asset_name}  {orig_w}x{orig_h}px")
    return {"result_b64": result_b64}


# ---------------------------------------------------------------------------
# POST /api/assets/approve  — save a previously-previewed asset to disk
# ---------------------------------------------------------------------------

@app.post("/api/assets/approve")
async def asset_approve(req: AssetApproveRequest):
    """
    Path C: save the approved image_b64 to static/assets/project/{asset_name}.png.
    Resizes to the slot's canonical dimensions, backs up the old file to history/.
    """
    if req.asset_name not in ASSET_SLOT_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown asset '{req.asset_name}'")

    import base64 as b64mod
    from PIL import Image as PILImage

    slot = next((s for s in ASSET_SLOTS if s["name"] == req.asset_name), None)
    w, h = slot["size"]

    img_bytes = b64mod.b64decode(req.image_b64)
    img = PILImage.open(BytesIO(img_bytes)).convert("RGBA")
    if img.size != (w, h):
        img = img.resize((w, h), PILImage.LANCZOS)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    png_path = ASSETS_DIR / f"{req.asset_name}.png"
    if png_path.exists():
        backup = HISTORY_DIR / f"{req.asset_name}_{ts}.png"
        shutil.copy2(png_path, backup)
        log.info(f"Backed up {req.asset_name}.png -> history/{backup.name}")

    buf = BytesIO()
    img.save(buf, "PNG")
    png_path.write_bytes(buf.getvalue())
    log.info(f"assets/approve OK — saved {req.asset_name}.png  {w}x{h}px")
    return {"ok": True, "asset_name": req.asset_name}


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/play — serve the generated playable ad HTML
# ---------------------------------------------------------------------------

@app.get("/runs/{run_id}/play", include_in_schema=False)
async def play_run(run_id: str):
    html_file = _run_dir(run_id) / "index.html"
    if not html_file.exists():
        raise HTTPException(status_code=404, detail=f"No HTML build found for run '{run_id}'.")
    return FileResponse(html_file, media_type="text/html")
