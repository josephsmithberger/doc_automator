"""
Screenshot Documentation Agent
--------------------------------
Give it an old screenshot + the doc page it came from.
Claude reads the navigation instructions from the doc, finds that screen
in your app, and captures a fresh screenshot matching the new UI.

Usage:
    python screenshot_agent.py \
        --screenshot old_screenshot.png \
        --doc path/to/doc_page.md \
        --app "MyApp" \
        --out docs/screenshots/new_screenshot.png

Requirements:
    pip install -r requirements.txt

macOS permissions needed (System Settings → Privacy & Security):
    ✅ Screen Recording  → Terminal
    ✅ Accessibility     → Terminal
Then restart Terminal.
"""

import anthropic
import pyautogui
import base64
import argparse
import os
import time
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Suppress the Python Launcher dock icon bounce on macOS
try:
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
except Exception:
    pass


# ── Helpers ──────────────────────────────────────────────────────────────────

MAX_IMAGE_BYTES = 4 * 1024 * 1024  # 4 MB — safely under the 5 MB API limit


def compress_image_for_api(img: Image.Image, preserve_dimensions: bool = False) -> tuple[str, str]:
    """Compress a PIL image to fit within the API size limit.
    Returns (base64_data, media_type).

    When preserve_dimensions=True (used for agent screenshots), dimensions are
    never changed — only JPEG quality is reduced. This keeps Claude's coordinate
    mapping accurate against the declared display size in the computer-use tool."""
    # Try JPEG at decreasing quality levels — aggressive enough to avoid resizing
    for quality in [85, 70, 55, 40, 25, 15]:
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
        if len(buf.getvalue()) <= MAX_IMAGE_BYTES:
            return base64.standard_b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"

    if preserve_dimensions:
        # Cannot resize — coordinates must stay valid. Return best effort at quality 10.
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=10, optimize=True)
        return base64.standard_b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"

    # Resizing is acceptable (e.g. encoding a static reference image).
    # Scale down progressively, keeping aspect ratio.
    scale = 0.75
    while scale > 0.2:
        new_size = (int(img.width * scale), int(img.height * scale))
        resized = img.resize(new_size, Image.LANCZOS)
        buf = BytesIO()
        resized.convert("RGB").save(buf, format="JPEG", quality=60, optimize=True)
        if len(buf.getvalue()) <= MAX_IMAGE_BYTES:
            return base64.standard_b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"
        scale -= 0.1

    # Last-resort fallback
    buf = BytesIO()
    img.convert("RGB").resize((1024, 768), Image.LANCZOS).save(buf, format="JPEG", quality=50)
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"


def encode_image(path: str) -> tuple[str, str]:
    """Return (base64_data, media_type) for a local image file.
    Compresses the image if it exceeds the API size limit."""
    img = Image.open(path)

    # Check raw file size first (fast path for small images)
    file_size = os.path.getsize(path)
    if file_size <= MAX_IMAGE_BYTES:
        format_lower = img.format.lower() if img.format else "png"
        media_type = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg",
                      "webp": "image/webp", "gif": "image/gif"}.get(format_lower, "image/png")
        with open(path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8"), media_type

    # File is too large — compress it
    print(f"  ⚠️  Image {file_size / 1024 / 1024:.1f} MB — compressing for API...")
    return compress_image_for_api(img)


def read_doc(path: str) -> str:
    """Read a doc file (markdown, txt, html) as plain text."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_retina_scale() -> float:
    """Return the HiDPI/Retina scale factor (2.0 on Retina Macs, 1.0 otherwise)."""
    try:
        screenshot = pyautogui.screenshot()
        logical_w, _ = pyautogui.size()
        return screenshot.width / logical_w
    except Exception:
        return 1.0


def take_screenshot() -> str:
    """Capture the full screen and return as a compressed base64 image."""
    screenshot = pyautogui.screenshot()
    b64, _ = compress_image_for_api(screenshot, preserve_dimensions=True)
    return b64


def save_screenshot(path: str):
    """Save a screenshot to disk."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    pyautogui.screenshot().save(path)
    print(f"  💾 Saved: {path}")

def execute_action(action_input: dict, scale: float = 1.0) -> list:
    """Execute a computer-use action and return a fresh screenshot.

    On Retina Macs the screenshots sent to Claude are at 2× pixel resolution,
    but PyAutoGUI expects logical-point coordinates. Divide all pixel coordinates
    from Claude by `scale` (typically 2.0 on Retina) before acting.
    """
    action = action_input.get("action")

    def to_logical(coord):
        """Convert a pixel coordinate (as Claude sees it) to a logical point."""
        return int(coord[0] / scale), int(coord[1] / scale)

    if action == "left_click":
        x, y = to_logical(action_input["coordinate"])
        pyautogui.click(x, y)
        time.sleep(0.3)

    elif action == "double_click":
        x, y = to_logical(action_input["coordinate"])
        pyautogui.doubleClick(x, y)
        time.sleep(0.3)

    elif action == "right_click":
        x, y = to_logical(action_input["coordinate"])
        pyautogui.rightClick(x, y)
        time.sleep(0.25)

    elif action == "mouse_move":
        x, y = to_logical(action_input["coordinate"])
        pyautogui.moveTo(x, y)
        time.sleep(0.1)

    elif action == "type":
        pyautogui.typewrite(action_input["text"], interval=0.02)
        time.sleep(0.15)

    elif action == "key":
        # API may send 'key' or 'keys' depending on version
        key_str = action_input.get("key") or action_input.get("keys", "")
        if key_str:
            keys = key_str.replace("+", " ")
            pyautogui.hotkey(*keys.split())
        time.sleep(0.2)

    elif action == "scroll":
        x, y = to_logical(action_input["coordinate"])
        direction = action_input.get("direction", "down")
        amount = action_input.get("amount", 3)
        pyautogui.scroll(amount if direction == "up" else -amount, x=x, y=y)
        time.sleep(0.2)

    # Always return current screen state
    screenshot = pyautogui.screenshot()
    screenshot_b64, screenshot_media_type = compress_image_for_api(screenshot, preserve_dimensions=True)
    return [{
        "type": "image",
        "source": {"type": "base64", "media_type": screenshot_media_type, "data": screenshot_b64}
    }]


# ── Core Agent ────────────────────────────────────────────────────────────────

def run_agent(
    app_name: str,
    old_screenshot_path: str,
    doc_path: str,
    output_path: str,
):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Load inputs
    old_img_b64, old_img_type = encode_image(old_screenshot_path)
    doc_text = read_doc(doc_path)
    screen_w, screen_h = pyautogui.size()          # logical points
    retina_scale = get_retina_scale()               # 2.0 on Retina, 1.0 otherwise
    pixel_w = int(screen_w * retina_scale)          # actual screenshot pixel width
    pixel_h = int(screen_h * retina_scale)          # actual screenshot pixel height

    print(f"\n📄 Doc loaded: {doc_path}")
    print(f"🖼  Old screenshot: {old_screenshot_path}")
    print(f"📐 Screen: {screen_w}×{screen_h} logical pts  ({pixel_w}×{pixel_h} px, scale={retina_scale:.1f}×)")
    print(f"🎯 Output: {output_path}\n")

    # Build the initial prompt with old screenshot + doc as context
    initial_message = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": (
                    f"You are a documentation screenshot agent for the app '{app_name}'.\n\n"
                    f"## Your job\n"
                    f"The app has a new UI. I need you to:\n"
                    f"1. Read the documentation excerpt below to understand WHERE this screenshot is taken\n"
                    f"2. Look at the OLD screenshot to understand WHAT the screen shows\n"
                    f"3. Navigate to that exact screen in the currently running app '{app_name}'\n"
                    f"4. Once you're on the right screen (matching the old screenshot's content), "
                    f"   say SCREENSHOT_READY and stop. I will save the screenshot.\n\n"
                    f"## Documentation excerpt\n"
                    f"```\n{doc_text}\n```\n\n"
                    f"## Old screenshot (for reference — shows what screen we need)\n"
                    f"The image below is the OLD screenshot that needs to be replaced:"
                )
            },
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": old_img_type,
                    "data": old_img_b64,
                }
            },
            {
                "type": "text",
                "text": (
                    f"Now take a screenshot of the current screen to see where we are, "
                    f"then navigate to the correct screen in '{app_name}'."
                )
            }
        ]
    }

    # Tell Claude the actual pixel dimensions of the screenshots it will receive.
    # On Retina displays this is 2× the logical size returned by pyautogui.size().
    tools = [
        {
            "type": "computer_20251124",
            "name": "computer",
            "display_width_px": pixel_w,
            "display_height_px": pixel_h,
            "display_number": 1,
        }
    ]

    messages = [initial_message]
    max_turns = 30  # Safety limit

    def prune_screenshots(msgs: list, keep_last: int = 2) -> list:
        """Replace screenshot images in old tool_result messages with a placeholder
        to prevent the request from growing too large (413 error)."""
        # Collect indices of tool_result messages that contain screenshots
        screenshot_indices = [
            i for i, m in enumerate(msgs)
            if m.get("role") == "user"
            and isinstance(m.get("content"), list)
            and any(
                isinstance(b, dict)
                and b.get("type") == "tool_result"
                and any(
                    isinstance(r, dict) and r.get("type") == "image"
                    for r in (b.get("content") or [])
                )
                for b in m["content"]
            )
        ]
        # Keep the last `keep_last` screenshots; prune the rest
        to_prune = set(screenshot_indices[:-keep_last]) if len(screenshot_indices) > keep_last else set()
        pruned = []
        for i, m in enumerate(msgs):
            if i not in to_prune:
                pruned.append(m)
                continue
            # Replace image content in tool_result with a text stub
            new_content = []
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    new_result_content = [
                        r if not (isinstance(r, dict) and r.get("type") == "image")
                        else {"type": "text", "text": "[screenshot pruned]"}
                        for r in (b.get("content") or [])
                    ]
                    new_content.append({**b, "content": new_result_content})
                else:
                    new_content.append(b)
            pruned.append({**m, "content": new_content})
        return pruned

    for turn in range(max_turns):
        response = client.beta.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            tools=tools,
            messages=messages,
            betas=["computer-use-2025-11-24"],
        )

        # Collect all content blocks for this turn
        tool_use_block = None
        for block in response.content:
            if block.type == "text":
                print(f"Claude: {block.text}")
                # Claude signals it's on the right screen
                if "SCREENSHOT_READY" in block.text:
                    print("\n✅ Claude found the screen!")
                    save_screenshot(output_path)
                    return

            elif block.type == "tool_use" and block.name == "computer":
                tool_use_block = block
                action = block.input.get("action")
                coord = block.input.get("coordinate", "")
                print(f"  → {action} {coord}")

        if tool_use_block:
            result = execute_action(tool_use_block.input, scale=retina_scale)
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use_block.id,
                    "content": result,
                }]
            })
            # Prune old screenshots to avoid 413 request-too-large errors
            messages = prune_screenshots(messages, keep_last=2)

        if response.stop_reason == "end_turn":
            # If Claude ended without saying SCREENSHOT_READY, save anyway
            print("\n⚠️  Agent finished without confirming. Saving current screen.")
            save_screenshot(output_path)
            return

    print(f"\n⚠️  Reached turn limit ({max_turns}). Saving current screen.")
    save_screenshot(output_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Replace a doc screenshot with a fresh one from the new UI."
    )
    parser.add_argument("--screenshot", required=True,
                        help="Path to the OLD screenshot (png/jpg)")
    parser.add_argument("--doc", required=True,
                        help="Path to the doc file containing navigation context (md/txt/html)")
    parser.add_argument("--app", required=True,
                        help="Name of the app to navigate (e.g. 'Slack')")
    parser.add_argument("--out", required=True,
                        help="Where to save the new screenshot (e.g. docs/screenshots/settings.png)")

    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise EnvironmentError("Set ANTHROPIC_API_KEY environment variable first.")

    run_agent(
        app_name=args.app,
        old_screenshot_path=args.screenshot,
        doc_path=args.doc,
        output_path=args.out,
    )


if __name__ == "__main__":
    main()