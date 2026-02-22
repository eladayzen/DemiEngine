"""
gemini.py — Wrapper for Google Gemini image API calls.

Handles:
  - enhance_prompt()    : Claude Vision suggests better prompts for Nanobanana
  - generate_images()   : Gemini image-to-image or text-to-image
  - replace_asset()     : Gemini image-to-image for a single asset

All image inputs/outputs are base64-encoded strings (no file I/O).
"""

import os
import base64
import anthropic
from io import BytesIO

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _b64_to_bytes(b64: str) -> bytes:
    """Strip data-URL prefix if present, then decode."""
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    return base64.b64decode(b64)


def _bytes_to_b64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def _get_gemini_client():
    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError:
        raise RuntimeError(
            "google-genai package not installed. Run: pip install google-genai"
        )
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set in environment / .env file")
    return genai.Client(api_key=api_key), gtypes


# ---------------------------------------------------------------------------
# enhance_prompt
# ---------------------------------------------------------------------------

def enhance_prompt(rough_prompt: str, screenshot_b64: str) -> list[str]:
    """
    Use Claude Vision to suggest 3 refined Nanobanana prompts based on
    a rough user description and a screenshot of the current build.

    Returns a list of 3 prompt strings.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    image_bytes = _b64_to_bytes(screenshot_b64)
    img_b64_clean = _bytes_to_b64(image_bytes)

    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=512,
        system=(
            "You are a creative director for mobile game advertisements. "
            "You receive a screenshot of a playable ad and a rough description of a visual change "
            "the operator wants. Your job is to write 3 specific, vivid image-generation prompts "
            "that would produce a great reference image for that change. "
            "Each prompt should be 1–2 sentences, highly specific, and suitable for an image-to-image AI. "
            "Return ONLY a JSON array of 3 strings, nothing else. Example: "
            '[\"prompt 1\", \"prompt 2\", \"prompt 3\"]'
        ),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_b64_clean,
                        },
                    },
                    {
                        "type": "text",
                        "text": f"Current screenshot is attached. The operator wants: \"{rough_prompt}\"\n"
                                "Write 3 refined image-generation prompts for Nanobanana.",
                    },
                ],
            }
        ],
    )

    import json
    raw = message.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    suggestions = json.loads(raw)
    if not isinstance(suggestions, list) or len(suggestions) < 1:
        raise ValueError("Claude did not return a valid list of prompts")
    return suggestions[:3]


# ---------------------------------------------------------------------------
# generate_images
# ---------------------------------------------------------------------------

def generate_images(
    prompt: str,
    reference_image_b64: str | None = None,
    num_variations: int = 2,
    additional_reference_images: list[str] | None = None,
) -> list[str]:
    """
    Call Gemini image generation.
    - If reference_image_b64 is provided: image-to-image edit
    - Otherwise: text-to-image
    - additional_reference_images: optional list of base64 images for additional context

    Returns list of base64-encoded PNG strings.
    """
    client, gtypes = _get_gemini_client()

    from PIL import Image as PILImage

    contents = []

    if reference_image_b64:
        img_bytes = _b64_to_bytes(reference_image_b64)
        pil_img = PILImage.open(BytesIO(img_bytes))
        contents.append(pil_img)

    # Add additional reference images (@ImageXX references)
    if additional_reference_images:
        for img_b64 in additional_reference_images:
            img_bytes = _b64_to_bytes(img_b64)
            pil_img = PILImage.open(BytesIO(img_bytes))
            contents.append(pil_img)

    contents.append(prompt)

    results = []
    for _ in range(num_variations):
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp-image-generation",
            contents=contents,
            config=gtypes.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                results.append(_bytes_to_b64(part.inline_data.data))
                break

    return results


# ---------------------------------------------------------------------------
# Asset role prompts — what each slot should look like as a game asset
# ---------------------------------------------------------------------------

_ASSET_ROLE_PROMPTS = {
    "background": (
        "A mobile card game background image, exactly {w}x{h} pixels, portrait orientation. "
        "Full-bleed environment scene, no UI elements, no text, no cards. "
        "Match the visual style, color palette, mood, and atmosphere shown in the reference image. "
        "Suitable for a mobile playable ad background."
    ),
    "card_back": (
        "A playing card back design, exactly {w}x{h} pixels. "
        "Decorative symmetrical pattern, centered composition with a border, no text, no numbers. "
        "Match the visual style and color palette of the reference image. "
        "Clean, print-quality card game asset."
    ),
    "felt": (
        "A card game table surface texture, exactly {w}x{h} pixels. "
        "Seamless fabric or material texture — no cards, no UI, no text. "
        "Match the color, mood, and material feel of the reference image. "
        "Suitable as a table felt / baize surface in a mobile card game."
    ),
}

_ASSET_ROLE_FALLBACK = (
    "A game UI asset, exactly {w}x{h} pixels. "
    "Match the visual style and color palette of the reference image. "
    "Clean, game-ready image, no text."
)


# ---------------------------------------------------------------------------
# generate_asset  (replaces replace_asset — generates fresh at exact dimensions)
# ---------------------------------------------------------------------------

def generate_asset(
    asset_name: str,
    width: int,
    height: int,
    reference_image_b64: str,
    annotations_b64: str | None = None,
) -> str:
    """
    Generate a brand-new game asset for the given slot, sized exactly width×height px,
    styled to match the reference image.

    Optionally composites annotations on top of the reference before sending.

    Returns base64-encoded PNG string of the new asset.
    """
    client, gtypes = _get_gemini_client()

    from PIL import Image as PILImage

    # Load reference image
    ref_bytes = _b64_to_bytes(reference_image_b64)
    ref_img   = PILImage.open(BytesIO(ref_bytes)).convert("RGBA")

    # Composite annotations onto reference if provided
    if annotations_b64:
        ann_bytes = _b64_to_bytes(annotations_b64)
        ann_img   = PILImage.open(BytesIO(ann_bytes)).convert("RGBA")
        ann_img   = ann_img.resize(ref_img.size, PILImage.LANCZOS)
        ref_img   = PILImage.alpha_composite(ref_img, ann_img)

    # Build role-specific prompt with exact dimensions
    template = _ASSET_ROLE_PROMPTS.get(asset_name, _ASSET_ROLE_FALLBACK)
    prompt   = template.format(w=width, h=height)

    response = client.models.generate_content(
        model="gemini-2.0-flash-exp-image-generation",
        contents=[ref_img, prompt],
        config=gtypes.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
        ),
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            raw_b64 = _bytes_to_b64(part.inline_data.data)
            # Resize output to exact target dimensions using PIL
            out_img = PILImage.open(BytesIO(_b64_to_bytes(raw_b64))).convert("RGBA")
            if out_img.size != (width, height):
                out_img = out_img.resize((width, height), PILImage.LANCZOS)
            buf = BytesIO()
            out_img.save(buf, "PNG")
            return _bytes_to_b64(buf.getvalue())

    raise RuntimeError(f"Gemini did not return an image for asset '{asset_name}'")
