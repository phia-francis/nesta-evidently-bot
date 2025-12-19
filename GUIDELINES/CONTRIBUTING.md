# Contributing to Nesta Evidently Bot

Thank you for your interest in contributing! We are building an AI-powered 'Test & Learn' assistant to help teams track assumptions and experiments directly in Slack.

## Getting Started

### Prerequisites
* Python 3.9+
* A Slack Workspace (for testing) with Socket Mode enabled.
* A Google Cloud Project with the Gemini API enabled.

### Local Development Setup

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/phia-francis/nesta-evidently-bot.git](https://github.com/phia-francis/nesta-evidently-bot.git)
    cd nesta-evidently-bot
    ```

2.  **Create a virtual environment:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment:**
    Copy the example environment file and fill in your keys.
    ```bash
    cp .env.example .env
    ```
    *Required keys:* `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_SIGNING_SECRET`, `GOOGLE_API_KEY`.

5.  **Run the Bot:**
    ```bash
    python app.py
    ```

## Architecture & Coding Standards

To maintain a production-ready codebase, please adhere to the following architectural patterns:

### 1. Modular Structure
* **`app.py`**: Contains *only* Slack event listeners (e.g., `@app.event`, `@app.command`). Keep logic minimal here.
* **`services/`**: All business logic goes here.
    * `ai_service.py`: For Google Gemini interactions.
    * `db_service.py`: For Supabase/Database interactions.
* **`blocks/`**: All Block Kit JSON payloads (UI) must be defined here as functions returning dictionaries.

### 2. Slack Bolt Best Practices
* Use the `ack()` function immediately for all commands and interactivity handlers to prevent timeouts.
* Use `say()` for simple text responses, but prefer `client.chat_postMessage` with `blocks` for rich UI.

### 3. Error Handling
* The bot must never crash silently. Wrap external API calls (Gemini, Database) in `try/except` blocks.
* If an API fails, send a user-friendly ephemeral message (e.g., "I'm having trouble reaching the AI brain right now.").

## Submitting a Pull Request

1.  **Branching**: Create a new branch for your feature (`feat/your-feature`) or bugfix (`fix/issue-description`).
2.  **Testing**: Ensure the bot starts and responds to the modified commands locally.
3.  **Secrets**: **NEVER** commit your `.env` file or any hardcoded API keys. Double-check your diff before pushing.
4.  **Description**: Clearly describe the problem you are solving and how you tested the solution.

## Code of Conduct

Please note that this project is released with a [Contributor Code of Conduct](CODE_OF_CONDUCT.md). By participating in this project you agree to abide by its terms.
