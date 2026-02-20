"""
generate_default_assets.py
Run once to generate realistic default assets for the card game.
Saves to static/assets/project/  (backing up any existing files first).

Usage:
    cd C:\Tests\PlayablePrtoto
    py scripts/generate_default_assets.py
"""

import sys, os, base64, shutil
from pathlib import Path
from io import BytesIO
from datetime import datetime

# ── Make sure project root is on path ──────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from PIL import Image as PILImage
from google import genai
from google.genai import types as gtypes

ASSETS_DIR  = ROOT / "static" / "assets" / "project"
HISTORY_DIR = ROOT / "static" / "assets" / "history"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ── Asset definitions ───────────────────────────────────────
ASSETS = [
    {
        "name":   "background",
        "size":   (390, 844),
        "prompt": (
            "A dark, moody card game background for a mobile app. "
            "Deep emerald green felt table surface extending to the edges. "
            "Soft vignette edges fading to near-black. "
            "Subtle wood-grain border around the edges of the table. "
            "No cards, no UI, no text. Portrait orientation 390x844 pixels. "
            "Photorealistic, cinematic lighting, high quality game asset."
        ),
    },
    {
        "name":   "card_back",
        "size":   (60, 84),
        "prompt": (
            "A classic playing card back design. "
            "Dark navy blue background. "
            "Intricate gold diamond lattice pattern covering the face. "
            "Thin white border around the edge. "
            "Elegant, symmetrical, ornate. "
            "No text, no numbers, no suits. "
            "Clean sharp card game asset, 60x84 pixels."
        ),
    },
    {
        "name":   "felt",
        "size":   (366, 560),
        "prompt": (
            "Top-down view of a green card table surface for a mobile game. "
            "Solid emerald green fabric with subtle textile grain. "
            "Flat overhead lighting, no shadows, no objects on top. "
            "Game asset background texture, 366x560 pixels."
        ),
    },
]

# ── Generate ────────────────────────────────────────────────
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

for asset in ASSETS:
    name   = asset["name"]
    w, h   = asset["size"]
    prompt = asset["prompt"]

    print(f"\n>> Generating {name} ({w}x{h})...")

    response = client.models.generate_content(
        model="gemini-2.0-flash-exp-image-generation",
        contents=[prompt],
        config=gtypes.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
        ),
    )

    img_data = None
    cand = response.candidates[0] if response.candidates else None
    if cand and cand.content and cand.content.parts:
        for part in cand.content.parts:
            if part.inline_data is not None:
                img_data = part.inline_data.data
                break

    if not img_data:
        print(f"  SKIP: No image returned for {name}")
        continue

    # Resize to exact target dimensions
    img = PILImage.open(BytesIO(img_data)).convert("RGBA")
    if img.size != (w, h):
        print(f"  Resizing from {img.size} -> ({w}, {h})")
        img = img.resize((w, h), PILImage.LANCZOS)

    dest = ASSETS_DIR / f"{name}.png"

    # Back up existing file
    if dest.exists():
        backup = HISTORY_DIR / f"{name}_{ts}.png"
        shutil.copy2(dest, backup)
        print(f"  Backed up old {name}.png -> history/")

    # Save
    img.save(dest, "PNG")
    print(f"  OK Saved {dest.name}  ({w}x{h}px)")

print("\nAll done. Restart the server and refresh the Visual Editor tab.")
