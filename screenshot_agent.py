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


# ── Helpers ──────────────────────────────────────────────────────────────────

def encode_image(path: str) -> tuple[str, str]:
    """Return (base64_data, media_type) for a local image file."""
    # Open image to detect actual format (not just extension)
    img = Image.open(path)
    format_lower = img.format.lower() if img.format else "png"
    
    # Map PIL format to media type
    format_map = {
        "png": "image/png",
        "jpeg": "image/jpeg",
        "jpg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }
    media_type = format_map.get(format_lower, "image/png")
    
    # Read and encode the file
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    
    return data, media_type


def read_doc(path: str) -> str:
    """Read a doc file (markdown, txt, html) as plain text."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def take_screenshot() -> str:
    """Capture the full screen and return as base64 PNG."""
    screenshot = pyautogui.screenshot()
    buf = BytesIO()
    screenshot.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def save_screenshot(path: str):
    """Save a screenshot to disk."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    pyautogui.screenshot().save(path)
    print(f"  💾 Saved: {path}")

def execute_action(action_input: dict) -> list:
    """Execute a computer-use action and return a fresh screenshot."""
    action = action_input.get("action")

    if action == "left_click":
        x, y = action_input["coordinate"]
        pyautogui.click(x, y)
        time.sleep(0.6)

    elif action == "double_click":
        x, y = action_input["coordinate"]
        pyautogui.doubleClick(x, y)
        time.sleep(0.6)

    elif action == "right_click":
        x, y = action_input["coordinate"]
        pyautogui.rightClick(x, y)
        time.sleep(0.5)

    elif action == "mouse_move":
        x, y = action_input["coordinate"]
        pyautogui.moveTo(x, y)
        time.sleep(0.2)

    elif action == "type":
        pyautogui.typewrite(action_input["text"], interval=0.04)
        time.sleep(0.3)

    elif action == "key":
        keys = action_input["key"].replace("+", " ")
        pyautogui.hotkey(*keys.split())
        time.sleep(0.4)

    elif action == "scroll":
        x, y = action_input["coordinate"]
        direction = action_input.get("direction", "down")
        amount = action_input.get("amount", 3)
        pyautogui.scroll(amount if direction == "up" else -amount, x=x, y=y)
        time.sleep(0.4)

    # Always return current screen state
    screenshot_b64 = take_screenshot()
    return [{
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": screenshot_b64}
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
    screen_w, screen_h = pyautogui.size()

    print(f"\n📄 Doc loaded: {doc_path}")
    print(f"🖼  Old screenshot: {old_screenshot_path}")
    print(f"📐 Screen: {screen_w}×{screen_h}")
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

    tools = [
        {
            "type": "computer_20251124",
            "name": "computer",
            "display_width_px": screen_w,
            "display_height_px": screen_h,
            "display_number": 1,
        }
    ]

    messages = [initial_message]
    max_turns = 30  # Safety limit

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
            result = execute_action(tool_use_block.input)
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use_block.id,
                    "content": result,
                }]
            })

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