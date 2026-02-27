# Documentation Automator

Automated screenshot capture using Claude's computer use API. Give it an old screenshot + documentation, and Claude will navigate your app to recreate it with the new UI.

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables:**
   ```bash
   cp .env.example .env
   ```
   
3. **Add your API key:**
   - Open `.env` file
   - Replace `your_anthropic_api_key_here` with your actual Anthropic API key
   - Get your API key from: https://console.anthropic.com/

4. **Grant macOS permissions** (required for screen automation):
   - System Settings → Privacy & Security → Screen Recording → Enable Terminal
   - System Settings → Privacy & Security → Accessibility → Enable Terminal
   - Restart Terminal after enabling

## Usage

```bash
python main.py \
    --screenshot old_screenshot.png \
    --doc path/to/doc_page.md \
    --app "YourAppName" \
    --out docs/screenshots/new_screenshot.png
```

**Example:**
```bash
python main.py \
    --screenshot docs/old/settings.png \
    --doc docs/user-guide.md \
    --app "Xogot" \
    --out docs/screenshots/settings.png
```

The agent will:
1. Read the documentation to understand where the screenshot is from
2. Look at the old screenshot to see what screen it shows
3. Navigate your app to find the matching screen
4. Capture a fresh screenshot with the new UI

## Security

⚠️ **Never commit your `.env` file!** It contains sensitive API keys.
- The `.gitignore` file prevents this automatically
- Only commit `.env.example` as a template
