from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from enum import Enum


# ---------------------------------------------------------------------------
# Mechanics Config
# ---------------------------------------------------------------------------

class MechanicsConfig(BaseModel):
    mechanics_version: str = "1.0"
    genre: str = "solitaire_simplified"
    input_type: Literal["tap", "drag", "both"] = "tap"
    card_move_speed: Literal["slow", "medium", "fast"] = "medium"
    animation_type: Literal["slide", "flip", "instant"] = "flip"
    highlight_valid_moves: bool = True
    auto_complete_enabled: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# Levels Config
# ---------------------------------------------------------------------------

class EnterAnimation(str, Enum):
    """
    How cards animate into the scene at the start of a level.
    shuffle_in : each card flies in from a random off-screen position, bottom rows first.
    drop_down  : all cards fall from above into position, bottom rows first.
    bulk       : all cards move together as one unit from slightly above.
    """
    shuffle_in = "shuffle_in"
    drop_down  = "drop_down"
    bulk       = "bulk"


class TableauCard(BaseModel):
    code:    str  = Field(description="Card code, e.g. '7H', 'AS', '10D', 'KS'")
    face_up: bool = True
    col:     int  = Field(description="Column index (0-based, left to right)")
    row:     int  = Field(description="Row index (0-based, top to bottom)")


class GridConfig(BaseModel):
    cell_width:  int   = Field(default=76,  description="Pixels per column")
    cell_height: int   = Field(default=100, description="Pixels per row")
    origin_x:    float = Field(default=0.5, description="Horizontal center of grid as fraction of stage width (0.0–1.0)")
    origin_y:    float = Field(default=0.18, description="Top of grid as fraction of stage height (0.0–1.0)")


class LevelLayout(BaseModel):
    foundation_card: str             = Field(description="The initial face-up card the player matches against. E.g. '7H'")
    tableau:         List[TableauCard] = Field(description="All cards on the board with their col/row positions")
    draw_pile:       List[str]        = Field(default=[], description="Cards available in the draw pile, drawn one at a time")
    grid:            GridConfig       = Field(default_factory=GridConfig)


class LevelTimings(BaseModel):
    win_screen_duration_ms:        int = 2000
    fail_screen_duration_ms:       int = 2000
    level_transition_duration_ms:  int = 1000


class LevelConfig(BaseModel):
    level_id:          int
    game_type:         Literal["solitaire_simplified"] = "solitaire_simplified"
    show_draw_pile:    bool           = True
    enter_animation:   EnterAnimation = EnterAnimation.shuffle_in
    enter_duration_ms: int            = Field(default=1200, description="Total ms from first card entering to all cards settled")
    layout:            LevelLayout
    timings:           LevelTimings   = Field(default_factory=LevelTimings)


class LevelsConfig(BaseModel):
    levels_version: str          = "1.0"
    genre:          str          = "solitaire_simplified"
    testing_mode:   bool         = Field(default=False, description="Show HUD debug overlay. Hidden in production builds.")
    total_levels:   int
    target_url:     str          = Field(default="https://yourapp.link/download", description="CTA destination URL")
    cta_text:       str          = Field(default="Play Now!", description="Text shown on the end-card CTA button")
    levels:         List[LevelConfig]


# ---------------------------------------------------------------------------
# Visual Config
# ---------------------------------------------------------------------------

class VisualConfig(BaseModel):
    visual_version:     str = "1.0"
    background_color:   str = "#1a472a"
    table_felt_color:   str = "#15803d"
    card_face_color:    str = "#ffffff"
    card_back_color:    str = "#1a237e"
    card_back_pattern:  Literal["solid", "stripes", "dots"] = "solid"
    card_border_color:  str = "#333333"
    highlight_color:    str = "#ffeb3b"
    button_color:       str = "#ff5722"
    button_text_color:  str = "#ffffff"
    primary_text_color: str = "#ffffff"
    font_family:        str = "Arial, sans-serif"
    ui_theme:           Literal["dark", "classic", "minimal"] = "dark"


# ---------------------------------------------------------------------------
# Seed (saved when randomization is used)
# ---------------------------------------------------------------------------

class SeedValues(BaseModel):
    mechanics: Optional[int] = None
    levels:    Optional[int] = None
    visual:    Optional[int] = None

class VariationAmounts(BaseModel):
    mechanics: float = Field(default=0.3, ge=0.0, le=1.0)
    levels:    float = Field(default=0.3, ge=0.0, le=1.0)
    visual:    float = Field(default=0.3, ge=0.0, le=1.0)

class SeedConfig(BaseModel):
    seed_version:      str              = "1.0"
    created_at:        str              = ""
    seeds:             SeedValues       = Field(default_factory=SeedValues)
    variation_amounts: VariationAmounts = Field(default_factory=VariationAmounts)


# ---------------------------------------------------------------------------
# Combined — all configs for a single run
# ---------------------------------------------------------------------------

class RunConfigs(BaseModel):
    mechanics: MechanicsConfig
    levels:    LevelsConfig
    visual:    VisualConfig
    seed:      Optional[SeedConfig] = None
