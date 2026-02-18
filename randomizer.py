"""
Variation-based randomization for each config section.
Every randomization uses a seed so results are reproducible.
"""
import colorsys
import random
from copy import deepcopy

from schemas import (
    MechanicsConfig,
    LevelsConfig,
    LevelConfig,
    LevelLayout,
    LevelTimings,
    GridConfig,
    VisualConfig,
    EnterAnimation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vary_literal(rng: random.Random, current: str, options: list, variation: float) -> str:
    """With probability = variation, pick a different option from the list."""
    if rng.random() < variation:
        others = [o for o in options if o != current]
        return rng.choice(others) if others else current
    return current


def _vary_bool(rng: random.Random, current: bool, variation: float) -> bool:
    return not current if rng.random() < variation else current


def _vary_int(rng: random.Random, current: int, low: int, high: int, variation: float) -> int:
    delta = int((high - low) * variation)
    new_val = current + rng.randint(-delta, delta)
    return max(low, min(high, new_val))


def _hex_to_hsl(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h, s, l


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def _vary_color(rng: random.Random, hex_color: str, variation: float) -> str:
    try:
        h, s, l = _hex_to_hsl(hex_color)
        h = (h + rng.uniform(-variation * 0.3, variation * 0.3)) % 1.0
        s = max(0.1, min(1.0, s + rng.uniform(-variation * 0.2, variation * 0.2)))
        l = max(0.1, min(0.9, l + rng.uniform(-variation * 0.15, variation * 0.15)))
        return _hsl_to_hex(h, s, l)
    except Exception:
        return hex_color  # fall back to original if color parsing fails


# ---------------------------------------------------------------------------
# Per-section randomizers
# ---------------------------------------------------------------------------

def randomize_mechanics(config: MechanicsConfig, variation: float, seed: int) -> MechanicsConfig:
    rng = random.Random(seed)
    return MechanicsConfig(
        mechanics_version=config.mechanics_version,
        genre=config.genre,
        game_type=config.game_type,
        input_type=_vary_literal(rng, config.input_type, ["tap", "drag", "both"], variation),
        card_move_speed=_vary_literal(rng, config.card_move_speed, ["slow", "medium", "fast"], variation),
        animation_type=_vary_literal(rng, config.animation_type, ["slide", "flip", "instant"], variation),
        highlight_valid_moves=_vary_bool(rng, config.highlight_valid_moves, variation * 0.4),
        auto_complete_enabled=_vary_bool(rng, config.auto_complete_enabled, variation * 0.2),
        notes=config.notes,
    )


def randomize_visual(config: VisualConfig, variation: float, seed: int) -> VisualConfig:
    rng = random.Random(seed)

    color_fields = [
        "background_color", "table_felt_color", "card_face_color",
        "card_back_color", "card_border_color", "highlight_color",
        "button_color", "button_text_color", "primary_text_color",
    ]

    data = config.dict()
    for field in color_fields:
        data[field] = _vary_color(rng, data[field], variation)

    data["card_back_pattern"] = _vary_literal(
        rng, config.card_back_pattern, ["solid", "stripes", "dots"], variation * 0.5
    )
    data["ui_theme"] = _vary_literal(
        rng, config.ui_theme, ["dark", "classic", "minimal"], variation * 0.5
    )

    return VisualConfig(**data)


def randomize_levels(config: LevelsConfig, variation: float, seed: int) -> LevelsConfig:
    """
    Varies timings, enter animations, and grid sizing per level.
    Card layouts are not randomized — preserving solvability.
    """
    rng = random.Random(seed)

    animation_options = [a.value for a in EnterAnimation]

    new_levels = []
    for level in config.levels:
        # Vary enter animation and duration
        new_animation = _vary_literal(rng, level.enter_animation.value, animation_options, variation * 0.6)
        new_duration  = _vary_int(rng, level.enter_duration_ms, 400, 2000, variation * 0.4)

        # Vary grid cell size slightly
        new_cell_w = _vary_int(rng, level.layout.grid.cell_width,  56, 110, variation * 0.3)
        new_cell_h = _vary_int(rng, level.layout.grid.cell_height, 76, 150, variation * 0.3)

        new_grid = GridConfig(
            cell_width=new_cell_w,
            cell_height=new_cell_h,
            origin_x=level.layout.grid.origin_x,
            origin_y=level.layout.grid.origin_y,
        )

        # Vary timings
        new_timings = LevelTimings(
            win_screen_duration_ms=_vary_int(
                rng, level.timings.win_screen_duration_ms, 1000, 5000, variation * 0.4),
            fail_screen_duration_ms=_vary_int(
                rng, level.timings.fail_screen_duration_ms, 1000, 5000, variation * 0.4),
            level_transition_duration_ms=_vary_int(
                rng, level.timings.level_transition_duration_ms, 500, 3000, variation * 0.4),
        )

        new_layout = LevelLayout(
            foundation_card=level.layout.foundation_card,
            tableau=level.layout.tableau,
            draw_pile=level.layout.draw_pile,
            grid=new_grid,
        )

        new_levels.append(LevelConfig(
            level_id=level.level_id,
            game_type=level.game_type,
            show_draw_pile=level.show_draw_pile,
            enter_animation=new_animation,
            enter_duration_ms=new_duration,
            layout=new_layout,
            timings=new_timings,
        ))

    return LevelsConfig(
        levels_version=config.levels_version,
        genre=config.genre,
        testing_mode=config.testing_mode,
        total_levels=config.total_levels,
        target_url=config.target_url,
        cta_text=config.cta_text,
        levels=new_levels,
    )
