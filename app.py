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
    {"name": "background", "description": "Full background image",       "size": (390, 844)},
    {"name": "card_back",  "description": "Card back face (face-down)",  "size": (60,  84)},
    {"name": "felt",       "description": "Table surface / felt texture", "size": (366, 560)},
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
    text_note: Optional[str] = None
    has_drawing: bool = False              # True when screenshot contains user-drawn marks baked in
    level_index: int = 0
    game_metadata: Optional[dict] = None   # game state metadata (level number, foundation, etc.)


class ReplaceAssetsRequest(BaseModel):
    asset_names: list[str]               # e.g. ["background", "card_back"]
    reference_image: str                 # base64 — target style reference
    annotations: Optional[str] = None   # base64 — drawing on reference


class AssetEditPreviewRequest(BaseModel):
    asset_name: str     # e.g. "background"
    prompt: str         # user's description of the desired change


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


@app.post("/api/visual/layout")
async def visual_layout(req: VisualLayoutRequest):  # noqa: F811
    """
    Path A endpoint: Claude Vision reads screenshot + optional annotations/reference/text
    and returns an updated LevelLayout reflecting the requested positional changes.
    """
    has_ann = bool(req.annotations)
    has_ref = bool(req.nanobanana_reference)
    log.info(f"POST /api/visual/layout — level={req.level_index}, has_drawing={req.has_drawing}, annotations={has_ann}, nanobanana_ref={has_ref}, note={repr((req.text_note or '')[:60])}")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured in .env")

    client = anthropic_sdk.Anthropic(api_key=api_key)

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

    content.append({"type": "text", "text": f"{context_text}\nUse the generate_level_layout tool to return the updated layout."})

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2048,
            system=VISUAL_LAYOUT_SYSTEM,
            tools=[GAMEPLAY_TOOL],
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": content}]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude API error: {e}")

    # Extract text reasoning and tool result from Claude's response
    tool_result = None
    reasoning_text = ""

    for block in response.content:
        if block.type == "text":
            reasoning_text += block.text + " "
        elif block.type == "tool_use" and block.name == "generate_level_layout":
            tool_result = block.input

    if not tool_result:
        raise HTTPException(status_code=500, detail="AI did not return a layout. Try adding more detail.")

    # Generate simple reasoning and complexity assessment
    reasoning_simple = reasoning_text.strip() if reasoning_text.strip() else "I've analyzed your request and created a new layout accordingly."

    # Assess complexity based on the layout changes
    tableau = tool_result.get("tableau", [])
    num_cards = len(tableau)
    num_cols = max((c["col"] for c in tableau), default=0) + 1
    draw_pile_count = len(tool_result.get("draw_pile", []))

    # Simple heuristic for complexity
    if num_cards <= 5 and num_cols <= 3 and draw_pile_count <= 3:
        complexity = "easy"
    elif num_cards >= 10 or num_cols >= 6 or draw_pile_count >= 8:
        complexity = "risky"
    else:
        complexity = "moderate"

    tableau = tool_result.get("tableau", [])
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
        }
    }
    log.info(f"visual/layout OK — foundation={layout.foundation_card}, {len(layout.tableau)} tableau cards")
    return result_payload


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

    results = generate_images(req.prompt, reference_image_b64=ref_b64, num_variations=1)
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
