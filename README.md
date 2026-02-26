# Documentation Automator

Automated screenshot capture using Claude's computer use API.

## Setup

1. **Install dependencies:**
   ```bash
   pip install anthropic pyautogui pillow python-dotenv
   ```

2. **Configure environment variables:**
   ```bash
   cp .env.example .env
   ```
   
3. **Add your API key:**
   - Open `.env` file
   - Replace `your_anthropic_api_key_here` with your actual Anthropic API key
   - Get your API key from: https://console.anthropic.com/

4. **Run the agent:**
   ```bash
   python screenshot_agent.py
   ```

## Security

⚠️ **Never commit your `.env` file!** It contains sensitive API keys.
- The `.gitignore` file prevents this automatically
- Only commit `.env.example` as a template

## Usage

The agent uses Claude's computer use capabilities to automate documentation tasks including taking screenshots.
