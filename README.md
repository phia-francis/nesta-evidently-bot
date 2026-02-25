# Nesta Evidently Bot

**Evidently** is an AI-powered 'Test & Learn' assistant for Slack, built to help innovation teams track assumptions, design experiments, and make evidence-based decisions. It implements Nesta's **Opportunity, Capability, Progress (OCP)** framework to turn unstructured conversations into rigorous project logic.

Powered by **Google Gemini**, **Slack Bolt**, and **Google Workspace**, Evidently acts as a "single source of truth" for your innovation projects.

---

## Table of Contents

- [Key Features](#-key-features)
- [Architecture](#️-architecture)
- [Getting Started](#-getting-started)
- [Configuration](#️-configuration)
- [API Endpoints](#-api-endpoints)
- [Commands](#-commands)
- [Testing](#-testing)
- [Deployment](#-deployment)
- [Security](#-security)
- [Generative AI Policy Compliance](#-generative-ai-policy-compliance-nesta-group)
- [Contributing](#-contributing)
- [License](#-license)

---

## ✨ Key Features

### 🧠 AI-Powered Insights

* **"So What?" Summariser:** Mention `@Evidently` in any Slack thread to get a structured summary, key decisions, and extracted OCP assumptions with confidence scores.
* **Auto-Extraction:** Automatically parses linked Google Docs to identify and log project assumptions.
* **Experiment Design:** Generates rapid test suggestions (e.g., Fake Door, Interviews) for any assumption.

### 📊 OCP Dashboard (Home Tab)

A persistent, visual dashboard in the App Home tab that tracks:

* **Project Health:** Visual "Confidence Rings" showing how validated your project is.
* **OCP Canvas:** Assumptions mapped to Opportunity, Capability, and Progress lanes.
* **Roadmap:** A Kanban-style view of assumptions prioritized by Now, Next, and Later.

### 🗳️ Decision Room

A real-time tool for team consensus:

* **Blind Voting:** Team members score assumptions on **Impact** vs. **Uncertainty** without seeing others' votes.
* **Visual Results:** Reveals a generated heatmap scatter plot to identify the "critical path" assumptions.

### 🔄 Active Persistence

* **Nudges:** Proactively identifies "stale" assumptions (untested for >14 days) and prompts owners to Validate, Archive, or Test them.
* **Drive Sync:** Keeps your Slack log in sync with your project documents.

### 🛠️ Integration & Export

* **Methods Toolkit:** Access Nesta's playbook methods and case studies directly in Slack via `/evidently-methods`.
* **One-Click Exports:** Generate Google Slides decks for stakeholder updates or Google Docs for project plans using `/evidently-export-slides` and `/evidently-draft-plan`.

---

## 🏗️ Architecture

The project is built with a modular, service-oriented architecture:

```
nesta-evidently-bot/
├── app.py                  # Application entry point (aiohttp web server)
├── config.py               # Centralised configuration and environment variables
├── config_manager.py       # Runtime configuration management
├── constants.py            # Shared constants
├── Procfile                # Process declaration for deployment
├── requirements.txt        # Python dependencies
├── alembic/                # Database migration scripts (Alembic)
│   └── versions/
├── controllers/
│   ├── slack_controller.py # Slack Bolt event/command handlers
│   └── web_controller.py   # aiohttp route definitions (health, OAuth, webhooks)
├── services/
│   ├── ai_service.py       # Google Gemini prompt engineering and PII redaction
│   ├── backup_service.py   # Project data backup utilities
│   ├── chart_service.py    # Dynamic chart generation
│   ├── db_service.py       # Data persistence layer (SQLAlchemy / PostgreSQL / SQLite)
│   ├── decision_service.py # Decision Room voting session logic
│   ├── drive_service.py    # Google Drive API wrapper
│   ├── google_auth_service.py    # Google OAuth token management
│   ├── google_service.py         # Google API client helpers
│   ├── google_workspace_service.py # Google Docs/Slides API wrapper
│   ├── ingestion_service.py      # Document ingestion pipeline
│   ├── integration_service.py    # Third-party integration orchestration
│   ├── knowledge_base.py         # OCP framework and methods definitions
│   ├── messenger_service.py      # Slack message dispatch helpers
│   ├── playbook_service.py       # Nesta Playbook method recommendations
│   ├── report_service.py         # Report generation logic
│   ├── scheduler_service.py      # APScheduler-based scheduled tasks
│   ├── schema_fixer.py           # Database schema migration checks
│   ├── sync_service.py           # Drive ↔ Slack synchronisation
│   └── toolkit_service.py        # Toolkit and methods catalogue
├── blocks/
│   ├── home_tab.py         # App Home tab layouts
│   ├── interactions.py     # Nudge blocks, AI summaries, Decision Room UI
│   ├── modals.py           # Pop-up dialog definitions
│   ├── modal_factory.py    # Modal builder helpers
│   ├── methods_ui.py       # Methods toolkit UI blocks
│   ├── nesta_ui.py         # Nesta-branded UI components
│   ├── onboarding.py       # Onboarding flow blocks
│   ├── ui_manager.py       # UI orchestration layer
│   └── ui_strings.py       # Centralised UI copy
├── utils/
│   └── diagnostic_utils.py # Diagnostic and debugging helpers
└── tests/
    ├── test_ai_service.py
    ├── test_gold_master_refactor.py
    ├── test_ingestion.py
    ├── test_integration_flow.py
    ├── test_onboarding.py
    └── test_routes.py
```

---

## 🚀 Getting Started

### Prerequisites

* Python 3.9+
* A Slack Workspace with a [Slack App](https://api.slack.com/apps) configured for **HTTP mode** (Events API).
* A Google Cloud Project with the **Gemini API** and **Drive/Docs/Slides APIs** enabled.

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/phia-francis/nesta-evidently-bot.git
   cd nesta-evidently-bot
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   Create a `.env` file in the project root (see [Configuration](#️-configuration) below).

5. **Run the bot:**
   ```bash
   python app.py
   ```
   The server starts on `http://0.0.0.0:3000` by default.

---

## ⚙️ Configuration

All configuration is managed through environment variables (loaded from `.env` via `python-dotenv`). See [`config.py`](config.py) for the full list.

### Required

| Variable | Description |
| --- | --- |
| `SLACK_BOT_TOKEN` | Bot User OAuth token (`xoxb-…`) |
| `SLACK_SIGNING_SECRET` | Slack app signing secret for request verification |
| `GOOGLE_API_KEY` | API key for Google Gemini |

### Google Workspace Integration

| Variable | Description |
| --- | --- |
| `GOOGLE_CLIENT_ID` | OAuth 2.0 client ID for Google Workspace |
| `GOOGLE_CLIENT_SECRET` | OAuth 2.0 client secret |
| `GOOGLE_REDIRECT_URI` | OAuth callback URL (e.g., `https://your-domain/auth/callback/google`) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full JSON content of the Google Service Account key |
| `GOOGLE_TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting stored Google tokens (required in production) |

### Asana Integration

| Variable | Description |
| --- | --- |
| `ASANA_TOKEN` | Asana Personal Access Token |
| `ASANA_WORKSPACE_ID` | Asana workspace ID |

### Database

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./evidently.db` | SQLAlchemy connection string (PostgreSQL recommended for production) |

### Server

| Variable | Default | Description |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `3000` | Server port |
| `ENVIRONMENT` | `development` | Set to `production` for stricter validation |

### Optional

| Variable | Default | Description |
| --- | --- | --- |
| `SLACK_APP_TOKEN` | — | App-level token (only needed if using Socket Mode) |
| `SLACK_APP_ID` | — | Slack App ID |
| `CONFIDENCE_THRESHOLD` | `0.8` | Minimum confidence score for assumption validation |
| `STALE_DAYS` | `14` | Days before an assumption is flagged as stale |
| `LEADERSHIP_CHANNEL` | `#leadership-updates` | Channel for leadership update notifications |
| `STANDUP_ENABLED` | `false` | Enable scheduled standup prompts |
| `STANDUP_HOUR` | `9` | Hour for scheduled standups (24h) |
| `STANDUP_MINUTE` | `30` | Minute for scheduled standups |
| `BACKUP_ENABLED` | `false` | Enable automatic backups |
| `BACKUP_CHANNEL` | — | Slack channel for backup notifications |
| `ADMIN_USERS` | — | Comma-separated list of Slack user IDs with admin privileges |

---

## 🌐 API Endpoints

The aiohttp web server exposes the following routes:

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Health check — returns `{"status": "ok"}` |
| `GET` | `/healthz` | Health check — returns `{"status": "ok"}` |
| `POST` | `/slack/events` | Slack Events API endpoint (handles URL verification and event dispatch) |
| `POST` | `/asana/webhook` | Asana webhook receiver |
| `GET` | `/auth/callback/google` | Google OAuth 2.0 callback |

---

## 🤖 Commands

| Command | Description |
| --- | --- |
| `/evidently-methods [stage]` | Get method recommendations from the Nesta Playbook (e.g., `/evidently-methods define`). |
| `/evidently-vote [imp] [unc]` | Cast a vote in an active Decision Room session (e.g., `/evidently-vote 5 3`). |
| `/evidently-link-doc [url]` | Connect a Google Doc to sync assumptions. |
| `/evidently-export-slides` | Generate a Google Slides presentation of your project status. |
| `/evidently-draft-plan` | Create a Google Doc project plan based on the OCP framework. |

---

## 🧪 Testing

The project uses [pytest](https://docs.pytest.org/) with [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) for async test support.

```bash
# Run the full test suite
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_routes.py -v
```

---

## 🚢 Deployment

The project includes a `Procfile` for deployment on platforms such as Heroku or Render:

```
web: python app.py
```

**Production checklist:**

1. Set `ENVIRONMENT=production` to enable strict validation of secrets.
2. Use a PostgreSQL `DATABASE_URL` instead of the default SQLite.
3. Set `GOOGLE_TOKEN_ENCRYPTION_KEY` to a valid Fernet key (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
4. Configure your Slack app's **Request URL** to point to `https://your-domain/slack/events`.
5. Configure your Google OAuth **Redirect URI** to `https://your-domain/auth/callback/google`.

---

## 🔒 Security

This project takes security seriously:

* **PII Redaction:** All text sent to the AI model is scrubbed of emails and phone numbers.
* **Least Privilege:** Google Drive access is scoped to read-only where possible.
* **Token Encryption:** Google OAuth tokens are encrypted at rest using Fernet symmetric encryption.
* See [SECURITY.md](SECURITY.md) for the full vulnerability reporting policy.
* For Nesta Group policy requirements (GenAI, data protection, cloud, incident response, web scraping), see [POLICIES.md](POLICIES.md).

---

## 🧭 Generative AI Policy Compliance (Nesta Group)

This project must be used in line with the Nesta Group Generative AI Policy. Key requirements include using approved tools like Google Gemini and protecting sensitive data.

For the full policy, see the [Generative AI Policy in POLICIES.md](POLICIES.md#1-generative-ai-policy-nesta-group).

---

## 🤝 Contributing

Please see [CONTRIBUTING.md](CONTRIBUTING.md) for our coding standards and pull request process.

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
