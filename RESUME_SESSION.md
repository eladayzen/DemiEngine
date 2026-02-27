# How to Resume Working on PlayablePrtoto

## Option A: Resume the exact conversation (keeps full chat history)
```
cd C:\Windows\system32
claude --resume
```
This will show you a list of recent sessions. Pick the one about PlayablePrtoto.
The session ID is: `80648e88-0cec-4f21-af11-0db7a1e42e3f`
Stored at: `C:\Users\USER\.claude\projects\C--Windows-system32\80648e88-0cec-4f21-af11-0db7a1e42e3f.jsonl`

## Option B: Start fresh but get Claude up to speed fast (recommended)

### Step 1: Start the game server
Open a PowerShell window and paste:
```
cd C:\Tests\PlayablePrtoto
py -m uvicorn app:app --port 8000
```
Leave this window open. The game UI will be at http://localhost:8000

### Step 2: Start Claude Code from the project folder
Open a NEW PowerShell window and paste:
```
cd C:\Tests\PlayablePrtoto
claude
```
Then tell Claude:
> Read the CLAUDE.md and RESUME_SESSION.md files in this project to get up to speed. I want to keep working on the Playable Ad Generator.

That's it! Claude will read the project docs and be ready to work.

---

## What This Project Is
- A browser-based tool that generates HTML5 solitaire playable ads (for AppLovin)
- Backend: Python FastAPI (app.py) on port 8000
- Frontend: Vanilla JS + PixiJS game engine
- AI: Anthropic Claude API + Google Gemini API for image generation
- API keys are in the `.env` file (already set up)

## Key Files
| File | What it does |
|------|-------------|
| `app.py` | Main backend (all API endpoints) |
| `static/index.html` | Main UI dashboard |
| `static/engine_template.html` | PixiJS game engine |
| `schemas.py` | Data models |
| `CLAUDE.md` | Full project spec (Claude reads this automatically) |
| `defaults/` | Default config files (mechanics, levels, visual) |
| `runs/` | All generated builds (783+) |

## Where We Left Off (Feb 2026)
- Fixed a bug where Smart Build changes weren't carrying forward to the next build
- All major features are complete (Multi-category Visual Editor, Smart Build, Asset Management)
- Still TODO: Path B asset requests, async image queue, localStorage auto-save

## Troubleshooting
- If `py` command not found: Python is at `C:\Python310\`
- If port 8000 is busy: kill the old process or use `py -m uvicorn app:app --port 8001`
- If Claude can't find files: make sure you `cd C:\Tests\PlayablePrtoto` first
