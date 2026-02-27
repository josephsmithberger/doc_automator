"""
doc_automator — Screenshot Documentation Agent

Given an old screenshot and the doc page it came from, Claude navigates
to that screen in your running app and captures a fresh screenshot.

Usage:
    python main.py --screenshot old.png --doc page.md --app MyApp --out new.png

macOS permissions required (System Settings → Privacy & Security):
    ✅ Screen Recording  → Terminal
    ✅ Accessibility     → Terminal
"""

import anthropic
import pyautogui
import base64
import argparse
import os
import sys
import time
import queue
import threading
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

try:
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
except Exception:
    pass

MAX_BYTES = 4 * 1024 * 1024
MAX_WIDTH = 1280


# ── Image helpers ──────────────────────────────────────────────────────────────

def compress(img: Image.Image, fixed_size: bool = False) -> tuple[str, str]:
    """Compress a PIL image to under MAX_BYTES. Returns (b64, media_type)."""
    for quality in [85, 70, 55, 40, 25, 15]:
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
        if len(buf.getvalue()) <= MAX_BYTES:
            return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"

    if fixed_size:
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=10, optimize=True)
        return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"

    scale = 0.75
    while scale > 0.2:
        resized = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        buf = BytesIO()
        resized.convert("RGB").save(buf, format="JPEG", quality=60, optimize=True)
        if len(buf.getvalue()) <= MAX_BYTES:
            return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"
        scale -= 0.1

    buf = BytesIO()
    img.resize((1024, 768), Image.LANCZOS).convert("RGB").save(buf, format="JPEG", quality=50)
    return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"


def encode_file(path: str) -> tuple[str, str]:
    """Encode a local image file as (b64, media_type), compressing if needed."""
    img = Image.open(path)
    if os.path.getsize(path) <= MAX_BYTES:
        fmt = (img.format or "png").lower()
        media = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                 "webp": "image/webp", "gif": "image/gif"}.get(fmt, "image/png")
        return base64.b64encode(open(path, "rb").read()).decode(), media
    print(f"  ⚠  {os.path.getsize(path)/1e6:.1f} MB image — compressing...")
    return compress(img)


def capture_screen(w: int, h: int, tw: int, th: int) -> tuple[str, str]:
    """Capture screen, normalize to logical size, then resize for tool display."""
    shot = pyautogui.screenshot()
    if (shot.width, shot.height) != (w, h):
        shot = shot.resize((w, h), Image.LANCZOS)
    if (w, h) != (tw, th):
        shot = shot.resize((tw, th), Image.LANCZOS)
    buf = BytesIO()
    shot.save(buf, format="PNG", optimize=True)
    data = buf.getvalue()
    if len(data) <= MAX_BYTES:
        return base64.b64encode(data).decode(), "image/png"
    return compress(shot, fixed_size=True)


def save_screenshot(path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    pyautogui.screenshot().save(path)
    print(f"  💾 Saved: {path}")


def display_size(lw: int, lh: int) -> tuple[int, int, float]:
    """Return (tool_w, tool_h, tool_to_logical_scale) capped at MAX_WIDTH."""
    scale = MAX_WIDTH / lw if lw > MAX_WIDTH else 1.0
    return int(lw * scale), int(lh * scale), scale


# ── Input handling ─────────────────────────────────────────────────────────────

_hints: queue.Queue = queue.Queue()

def _listen():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        if line.strip():
            _hints.put(line.strip())

def start_hint_listener():
    threading.Thread(target=_listen, daemon=True).start()

def drain_hints() -> str:
    parts = []
    while not _hints.empty():
        try: parts.append(_hints.get_nowait())
        except queue.Empty: break
    return "\n".join(parts)


# ── Action execution ───────────────────────────────────────────────────────────

_KEY_MAP = {
    "super": "command", "cmd": "command", "meta": "command",
    "control": "ctrl", "return": "enter", "esc": "escape",
    "del": "delete", "pgup": "pageup", "pgdn": "pagedown", "spacebar": "space",
}

def _norm_key(k: str) -> str:
    return _KEY_MAP.get(k.strip().lower(), k.strip().lower())


def execute_action(inp: dict, lw: int, lh: int, tw: int, th: int, scale: float = 1.0) -> list:
    """Run a computer-use action and return a screenshot result block."""
    action = inp.get("action")

    def to_logical(coord):
        x = max(0, min(lw - 1, int(coord[0] / scale)))
        y = max(0, min(lh - 1, int(coord[1] / scale)))
        return x, y

    if action == "left_click":
        pyautogui.click(*to_logical(inp["coordinate"])); time.sleep(0.3)
    elif action == "double_click":
        pyautogui.doubleClick(*to_logical(inp["coordinate"])); time.sleep(0.3)
    elif action == "right_click":
        pyautogui.rightClick(*to_logical(inp["coordinate"])); time.sleep(0.25)
    elif action == "mouse_move":
        pyautogui.moveTo(*to_logical(inp["coordinate"])); time.sleep(0.1)
    elif action == "type":
        pyautogui.typewrite(inp["text"], interval=0.02); time.sleep(0.15)
    elif action == "key":
        keys = [_norm_key(p) for p in (inp.get("key") or inp.get("keys", "")).replace("+", " ").split() if p.strip()]
        if len(keys) == 1: pyautogui.press(keys[0])
        elif keys: pyautogui.hotkey(*keys)
        time.sleep(0.2)
    elif action == "scroll":
        x, y = to_logical(inp.get("coordinate", [lw // 2, lh // 2]))
        amt = inp.get("amount", 3)
        pyautogui.scroll(amt if inp.get("direction", "down") == "up" else -amt, x=x, y=y)
        time.sleep(0.2)

    b64, media = capture_screen(lw, lh, tw, th)
    return [{"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}}]


# ── Agent ──────────────────────────────────────────────────────────────────────

def prune_screenshots(msgs: list, keep: int = 2) -> list:
    """Replace old inline screenshots with a stub to keep request size down."""
    def has_screenshot(m):
        return (m.get("role") == "user"
                and isinstance(m.get("content"), list)
                and any(b.get("type") == "tool_result"
                        and any(r.get("type") == "image" for r in (b.get("content") or []))
                        for b in m["content"] if isinstance(b, dict)))

    indices = [i for i, m in enumerate(msgs) if has_screenshot(m)]
    stale = set(indices[:-keep])

    result = []
    for i, m in enumerate(msgs):
        if i not in stale:
            result.append(m)
            continue
        new_content = []
        for b in m["content"]:
            if b.get("type") == "tool_result":
                pruned = [r if r.get("type") != "image" else {"type": "text", "text": "[screenshot pruned]"}
                          for r in (b.get("content") or [])]
                new_content.append({**b, "content": pruned})
            else:
                new_content.append(b)
        result.append({**m, "content": new_content})
    return result


def run_agent(app: str, screenshot: str, doc: str, output: str,
              context: str = "", model: str = "claude-sonnet-4-6",
              system: str = "", prompt: str = ""):

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    old_b64, old_type = encode_file(screenshot)
    doc_text = open(doc, encoding="utf-8").read()
    lw, lh = pyautogui.size()
    tw, th, scale = display_size(lw, lh)

    def read_or_inline(val):
        return open(val, encoding="utf-8").read() if val and os.path.isfile(val) else val

    context_text = read_or_inline(context)
    system_text  = read_or_inline(system)

    print(f"\n📄 Doc:    {doc}")
    print(f"🖼  Old:    {screenshot}")
    print(f"🎯 Output: {output}")
    print(f"🤖 Model:  {model}")
    print(f"📐 Screen: {lw}×{lh}  (tool: {tw}×{th}, scale={scale:.3f})")
    print(f"\n💡 Type a hint and press Enter at any time to guide the agent.\n")

    ctx_section = f"## App Context\n{context_text}\n\n" if context_text else ""

    initial = {
        "role": "user",
        "content": [
            {"type": "text", "text": (
                f"You are a documentation screenshot agent for '{app}'.\n\n"
                f"{ctx_section}"
                f"## Task\n"
                f"1. Read the doc excerpt to understand WHERE this screenshot is taken.\n"
                f"2. Study the old screenshot to understand WHAT the screen shows.\n"
                f"3. Navigate to that exact screen in the running app '{app}'.\n"
                f"4. Once on the right screen, say SCREENSHOT_READY and stop.\n\n"
                f"## Doc excerpt\n```\n{doc_text}\n```\n\n"
                f"## Old screenshot (for reference):"
            )},
            {"type": "image", "source": {"type": "base64", "media_type": old_type, "data": old_b64}},
            {"type": "text", "text": (
                f"Take a screenshot to see the current state, then navigate to the right screen in '{app}'."
                + (f"\n\n{prompt}" if prompt else "")
            )},
        ]
    }

    # Claude 4.6 (Sonnet/Opus) use computer_20251124, Haiku 4.5 uses computer_20250124
    is_new_model = "4.6" in model.lower() or "4-6" in model.lower()
    tool_type = "computer_20251124" if is_new_model else "computer_20250124"
    beta_version = "computer-use-2025-11-24" if is_new_model else "computer-use-2025-01-24"
    
    tools = [{"type": tool_type, "name": "computer",
              "display_width_px": tw, "display_height_px": th, "display_number": 1}]
    messages = [initial]
    start_hint_listener()

    for turn in range(30):
        response = client.beta.messages.create(
            model=model, max_tokens=4096, tools=tools, messages=messages,
            betas=[beta_version],
            **({"system": system_text} if system_text else {}),
        )

        tool_block = None
        for block in response.content:
            if block.type == "text":
                print(f"Claude: {block.text}")
                if "SCREENSHOT_READY" in block.text:
                    print("\n✅ Found the screen!")
                    save_screenshot(output)
                    return
            elif block.type == "tool_use" and block.name == "computer":
                tool_block = block
                print(f"  → {block.input.get('action')} {block.input.get('coordinate', '')}")

        if tool_block:
            result = execute_action(tool_block.input, lw, lh, tw, th, scale)
            messages.append({"role": "assistant", "content": response.content})
            user_content = [{"type": "tool_result", "tool_use_id": tool_block.id, "content": result}]
            if hint := drain_hints():
                print(f"\n💡 Hint: {hint}")
                user_content.append({"type": "text", "text": f"User hint: {hint}"})
            messages.append({"role": "user", "content": user_content})
            messages = prune_screenshots(messages)

        if response.stop_reason == "end_turn":
            print("\n⚠  Agent finished without confirming. Saving current screen.")
            save_screenshot(output)
            return

    print("\n⚠  Turn limit reached. Saving current screen.")
    save_screenshot(output)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Replace a doc screenshot with a fresh one from the new UI.")
    p.add_argument("--screenshot", required=True, help="Path to the old screenshot (png/jpg)")
    p.add_argument("--doc",        required=True, help="Doc file with navigation context (md/txt/html)")
    p.add_argument("--app",        default="Xogot", help="App name (default: Xogot)")
    p.add_argument("--out",        required=True, help="Output path for the new screenshot")
    p.add_argument("--context",    default="", help="Extra app context (string or path to file)")
    p.add_argument("--model",      default="claude-sonnet-4-6", help="Anthropic model (default: claude-sonnet-4-6)")
    p.add_argument("--system",     default="", help="System prompt (string or path to file)")
    p.add_argument("--prompt",     default="", help="Extra instruction appended to the initial message")
    args = p.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Error: ANTHROPIC_API_KEY environment variable is not set.")

    run_agent(app=args.app, screenshot=args.screenshot, doc=args.doc, output=args.out,
              context=args.context, model=args.model, system=args.system, prompt=args.prompt)


if __name__ == "__main__":
    main()
