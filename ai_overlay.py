"""
AI Overlay v2 for Windows - hotkey -> bottom-center overlay; talk / type / look at your screen / control it.

What's new
  * Streaming voice replies (ElevenLabs or any OpenAI-compatible TTS), sentence-by-sentence so speech starts
    while the model is still writing. Optional fast Whisper-style speech-to-text (e.g. Groq) for text-only models.
  * Summarize  = one-shot, READ-ONLY summary of the screen / selected area.
    Screen control = live mode: fresh screenshot every turn + the assistant may click, drag, scroll, type.
  * Persistent long-term memory (memory.json).
  * Any number of providers: OpenRouter, Gemini, OpenAI, Groq, Ollama, LM Studio or fully custom endpoints.
  * Encrypted vault (vault.bin, scrypt + Fernet). The model NEVER sees vault data: it can only ask for an entry,
    and a local master-password prompt is shown. The reveal happens locally and is never sent to any AI.
  * Canvas: shapes (triangles, circles, polygons...) and function plots (sin(x), x**2 ...), pan/zoom/pen/save.
  * "Open / close Spotify, Chrome, Google, YouTube, Notepad ..." by voice or text.
  * Collapsible AI orb: the overlay opens as a breathing, glowing orb docked where you like (Settings > Orb, or drag it);
    hovering opens the controls, which stay open. While the AI thinks it morphs back to the orb with a compact status pill.
    The chat grows out of the orb and folds back into it; one shared accent colour (or independent orb / chat colours)
    tints the orb, its glow, the pill, the chat panel, its focus ring, buttons and highlights - all live, no restart.
  * Explain / Summarize / Translate draw a teacher-on-a-whiteboard walkthrough: step cards, an animated pointer line
    and a highlighted frame on the exact element, with next / back / read-aloud / dismiss controls.

pip install PyQt6 requests keyboard sounddevice numpy pyautogui cryptography
Run: python ai_overlay.py   (rename to .pyw to hide the console)
Emergency stop for any automation: Ctrl+Alt+X (rebindable) or fling the mouse into a screen corner.

The program is split into the ai_overlay_lib package (core, accounts, system, voice, widgets, connectors,
panel, chat, dialogs, app). This file stays the entry point and keeps the original flat import surface:
`import ai_overlay` still exposes every class and helper it used to.
"""

from ai_overlay_lib.core import *          # noqa: F401,F403  (one flat namespace, as before the split)
from ai_overlay_lib.accounts import *      # noqa: F401,F403
from ai_overlay_lib.system import *        # noqa: F401,F403
from ai_overlay_lib.voice import *         # noqa: F401,F403
from ai_overlay_lib.widgets import *       # noqa: F401,F403
from ai_overlay_lib.connectors import *    # noqa: F401,F403
from ai_overlay_lib.panel import *         # noqa: F401,F403
from ai_overlay_lib.chat import *          # noqa: F401,F403
from ai_overlay_lib.dialogs import *       # noqa: F401,F403
from ai_overlay_lib.app import main        # noqa: F401
from ai_overlay_lib.core import (CFG_PATH, BUNDLED_CFG, MEM_PATH, USAGE_PATH, VAULT_PATH,  # noqa: F401
                                 BASE, PKG_DIR)

if __name__ == "__main__":
    main()
