import anthropic
import pyautogui
import base64
import json
import os
import time
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

def take_screenshot() -> str:
    """Take a screenshot and return as base64."""
    screenshot = pyautogui.screenshot()
    buffer = BytesIO()
    screenshot.save(buffer, format="PNG")
    return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

def save_screenshot(name: str):
    """Save a named screenshot to disk."""
    screenshot = pyautogui.screenshot()
    path = f"docs/screenshots/{name}.png"
    os.makedirs("docs/screenshots", exist_ok=True)
    screenshot.save(path)
    print(f"  ✅ Saved: {path}")

def run_computer_use_agent(task: str):
    """Run Claude with computer use tools to complete a documentation task."""
    
    tools = [
        {
            "type": "computer_20241022",
            "name": "computer",
            "display_width_px": pyautogui.size().width,
            "display_height_px": pyautogui.size().height,
            "display_number": 1,
        }
    ]

    messages = [
        {
            "role": "user",
            "content": task
        }
    ]

    print(f"\n🤖 Starting task: {task[:80]}...")

    while True:
        response = client.beta.messages.create(
            model="claude-opus-4-5-20251101",
            max_tokens=4096,
            tools=tools,
            messages=messages,
            betas=["computer-use-2024-10-22"],
        )

        # Process response blocks
        for block in response.content:
            if block.type == "text":
                print(f"Claude: {block.text}")
            
            elif block.type == "tool_use" and block.name == "computer":
                action = block.input.get("action")
                print(f"  → Action: {action}")

                # Execute the action
                result = execute_action(block.input)
                
                # Add assistant message and tool result to history
                messages.append({"role": "assistant", "content": response.content})
                messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    }]
                })
                break  # Re-enter loop with updated messages

        if response.stop_reason == "end_turn":
            print("✅ Task complete.")
            break

def execute_action(action_input: dict) -> list:
    """Execute a computer use action and return the screenshot result."""
    action = action_input.get("action")

    if action == "screenshot":
        pass  # Just take a screenshot below

    elif action == "left_click":
        x, y = action_input["coordinate"]
        pyautogui.click(x, y)
        time.sleep(0.5)

    elif action == "double_click":
        x, y = action_input["coordinate"]
        pyautogui.doubleClick(x, y)
        time.sleep(0.5)

    elif action == "right_click":
        x, y = action_input["coordinate"]
        pyautogui.rightClick(x, y)
        time.sleep(0.5)

    elif action == "type":
        pyautogui.typewrite(action_input["text"], interval=0.05)
        time.sleep(0.3)

    elif action == "key":
        pyautogui.hotkey(*action_input["key"].split("+"))
        time.sleep(0.3)

    elif action == "scroll":
        x, y = action_input["coordinate"]
        direction = action_input.get("direction", "down")
        amount = action_input.get("amount", 3)
        pyautogui.scroll(amount if direction == "up" else -amount, x=x, y=y)
        time.sleep(0.3)

    elif action == "mouse_move":
        x, y = action_input["coordinate"]
        pyautogui.moveTo(x, y)

    # Always return a fresh screenshot as the result
    screenshot_b64 = take_screenshot()
    return [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": screenshot_b64}}]


# ─── MAIN: Define your documentation tasks ───────────────────────────────────

if __name__ == "__main__":
    
    APP_NAME = "YourApp"  # ← Change this

    tasks = [
        f"""
        Open the application '{APP_NAME}'. 
        Once it's fully loaded and the main window is visible, 
        take a screenshot and tell me when you can see it clearly.
        """,
        
        f"""
        The app '{APP_NAME}' should already be open. 
        Navigate to the Settings screen (look for a gear icon or Settings menu item).
        Once you're on the Settings screen, describe what you see.
        """,
        
        # Add more tasks for each screen you want to document
    ]

    for i, task in enumerate(tasks):
        run_computer_use_agent(task)
        # Save screenshot after each task
        save_screenshot(f"screen_{i+1:02d}")
        time.sleep(1)