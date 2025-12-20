# Contributing to Nesta Evidently Bot

Thank you for your interest in contributing! We are building an AI-powered 'Test & Learn' assistant to help teams track assumptions and experiments directly in Slack.

## Getting Started

### Prerequisites

* Python 3.9+
* A Slack Workspace (for testing) with Socket Mode enabled.
* A Google Cloud Project with the Gemini API enabled.
* A Google Cloud Service Account (for Drive and Workspace integrations).

### Local Development Setup

1. **Clone the repository:**
```bash
git clone https://github.com/phia-francis/nesta-evidently-bot.git
cd nesta-evidently-bot

```


2. **Create a virtual environment:**
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate

```


3. **Install dependencies:**
```bash
pip install -r requirements.txt

```


4. **Configure Environment:**
Copy the example environment file and fill in your keys.
```bash
cp .env.example .env

```


**Required Environment Variables:**
* `SLACK_BOT_TOKEN`: Your Bot User OAuth Token.
* `SLACK_APP_TOKEN`: Your App-Level Token (for Socket Mode).
* `SLACK_SIGNING_SECRET`: Your App's Signing Secret.
* `GOOGLE_API_KEY`: API Key for Google Gemini.
* `GOOGLE_SERVICE_ACCOUNT_JSON`: The full JSON content of your Google Service Account key (required for Drive/Docs integrations).


**Optional/Future Variables:**
* `SUPABASE_URL` & `SUPABASE_KEY`: For persistent database storage (currently optional/in-memory).
* `CONFIDENCE_THRESHOLD`: (Default: 0.8)
* `STALE_DAYS`: (Default: 14)


5. **Run the Bot:**
```bash
python app.py

```



## Architecture & Coding Standards

To maintain a production-ready codebase, please adhere to the following architectural patterns:

### 1. Modular Structure

* **`app.py`**: Contains *only* Slack event listeners (e.g., `@app.event`, `@app.command`). Keep logic minimal here and delegate to services.
* **`services/`**: All business logic goes here.
* `ai_service.py`: For Google Gemini interactions and prompt engineering.
* `chart_service.py`: For generating dynamic charts (e.g., QuickChart).
* `db_service.py`: For data persistence (currently in-memory/Supabase compatible).
* `decision_service.py`: Manages decision room sessions and voting logic.
* `drive_service.py` & `google_workspace_service.py`: Wrappers for Google Drive, Docs, and Slides APIs.
* `knowledge_base.py`: Static definitions for the OCP framework and methods.


* **`blocks/`**: All Block Kit JSON payloads (UI) must be defined here as functions returning dictionaries.
* `home_tab.py`: Layouts for the App Home.
* `interactions.py`: Nudge blocks, AI summaries, and decision room UI.
* `modals.py`: Pop-up dialogs for inputs.



### 2. Slack Bolt Best Practices

* Use the `ack()` function immediately for all commands and interactivity handlers to prevent timeouts.
* Use `say()` for simple text responses, but prefer `client.chat_postMessage` with `blocks` for rich UI.
* For long-running tasks (like AI analysis), verify you are not blocking the thread; use `asyncio` features appropriately.

### 3. Error Handling

* The bot must never crash silently. Wrap external API calls (Gemini, Google Drive) in `try/except` blocks.
* If an API fails, send a user-friendly ephemeral message (e.g., "I'm having trouble reaching the AI brain right now.").

## Submitting a Pull Request

1. **Branching**: Create a new branch for your feature (`feat/your-feature`) or bugfix (`fix/issue-description`).
2. **Testing**: Ensure the bot starts and responds to the modified commands locally.
3. **Secrets**: **NEVER** commit your `.env` file or any hardcoded API keys. Double-check your diff before pushing.
4. **Description**: Clearly describe the problem you are solving and how you tested the solution.

## Code of Conduct

Please note that this project is released with a [Contributor Code of Conduct](https://www.google.com/search?q=GUIDELINES/CODE_OF_CONDUCT.md). By participating in this project you agree to abide by its terms.
