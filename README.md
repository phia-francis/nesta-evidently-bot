# Nesta Evidently Bot

**Evidently** is an AI-powered 'Test & Learn' assistant for Slack, built to help innovation teams track assumptions, design experiments, and make evidence-based decisions. It implements Nesta's **Opportunity, Capability, Progress (OCP)** framework to turn unstructured conversations into rigorous project logic.

Powered by **Google Gemini**, **Slack Bolt**, and **Google Workspace**, Evidently acts as a "single source of truth" for your innovation projects.

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

## 🏗️ Architecture

The project is built with a modular, service-oriented architecture:

* **`app.py`**: Entry point handling all Slack events, commands, and shortcuts.
* **`services/`**: Business logic isolated from the UI.
* `ai_service.py`: Google Gemini prompt engineering and PII redaction.
* `drive_service.py` & `google_workspace_service.py`: Google Drive/Docs/Slides API wrappers.
* `decision_service.py`: Logic for the Decision Room voting sessions.
* `chart_service.py`: Dynamic chart generation using QuickChart.io.
* `db_service.py`: Data persistence layer (compatible with Supabase).


* **`blocks/`**: Slack Block Kit UI components (`home_tab.py`, `interactions.py`, `modals.py`).

## 🚀 Getting Started

### Prerequisites

* Python 3.9+
* A Slack Workspace with Socket Mode enabled.
* A Google Cloud Project with the **Gemini API** and **Drive/Docs/Slides APIs** enabled.

### Installation

1. **Clone the repository:**
```bash
git clone https://github.com/phia-francis/nesta-evidently-bot.git
cd nesta-evidently-bot

```


2. **Install dependencies:**
```bash
pip install -r requirements.txt

```


3. **Configure Environment:**
Create a `.env` file with the following keys (see `config.py`):
```ini
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=...
GOOGLE_API_KEY=AIza...
GOOGLE_SERVICE_ACCOUNT_JSON={...}

```


4. **Run the Bot:**
```bash
python app.py

```



## 🤖 Commands

| Command | Description |
| --- | --- |
| `/evidently-methods [stage]` | Get method recommendations from the Nesta Playbook (e.g., `/evidently-methods define`). |
| `/evidently-vote [imp] [unc]` | Cast a vote in an active Decision Room session (e.g., `/evidently-vote 5 3`). |
| `/evidently-link-doc [url]` | Connect a Google Doc to sync assumptions. |
| `/evidently-export-slides` | Generate a Google Slides presentation of your project status. |
| `/evidently-draft-plan` | Create a Google Doc project plan based on the OCP framework. |

## 🔒 Security

This project takes security seriously:

* **PII Redaction:** All text sent to the AI model is scrubbed of emails and phone numbers.
* **Least Privilege:** Google Drive access is scoped to read-only where possible.
* See [SECURITY.md](https://www.google.com/search?q=GUIDELINES/SECURITY.md) for full policy.

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](https://www.google.com/search?q=GUIDELINES/CONTRIBUTING.md) for our coding standards and pull request process.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](https://www.google.com/search?q=GUIDELINES/LICENSE) file for details.
