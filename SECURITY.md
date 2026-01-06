# Security Policy

The **Nesta Evidently Bot** processes internal communication data and interfaces with external AI services (Google Gemini) and cloud databases (Supabase). Ensuring the privacy and security of this data is our top priority.

## Nesta Group Generative AI Policy Compliance

Use of GenAI in this project must follow the Nesta Group Generative AI Policy:

* **Default tool:** Google Gemini is the approved default GenAI tool for business use.
* **Approved exceptions only:** Any non-Gemini GenAI tool requires approval from your line manager and the Technology team.
* **No sensitive input to unapproved tools:** Personal data and confidential information must not be entered into unapproved GenAI tools.
* **Responsible use:** Document risk assessments, check contractual requirements, be transparent about GenAI use, and ensure human review/judgment.
* **DPIA requirement:** If Gemini processes personal data, complete a DPIA before use.
* **Policy updates:** Review the latest policy regularly as it may change.

Questions about the policy should be directed to the Applied Research & Innovation Director.

## Other Nesta Group Policies

This repository must also comply with Nesta Group policies on data protection, security incident management, cloud services, software development standards, and web scraping. See [POLICIES.md](POLICIES.md) for the consolidated summary and escalation points.

## Supported Versions

We currently support security updates for the latest version of the main branch.

| Version | Supported |
| --- | --- |
| Main | :white_check_mark: |

## Reporting a Vulnerability

**Do not open public GitHub issues for security vulnerabilities.**

If you have discovered a security vulnerability, please report it privately:

1. **Email**: Send a detailed report to the project maintainer (e.g. the repo owner).
2. **Content**: Please include:
* Type of issue (e.g., Prompt Injection, PII Leakage, Token Exposure).
* Full paths of source files involved.
* Step-by-step instructions to reproduce the issue.
* Proof-of-concept code (if applicable).



## Critical Areas of Concern

We are particularly interested in reports regarding:

### 1. AI Safety & Prompt Injection

The bot uses Google Gemini to analyse Slack threads. We employ input sanitisation, but we welcome reports on:

* **Prompt Injection/Jailbreaking**: Manipulation of the AI input to bypass safety filters or ignore system instructions.
* **Context Exfiltration**: Tricks to make the AI reveal parts of its system prompt or previous context.

### 2. Data Privacy (PII)

* **PII Redaction**: The bot includes a regex-based PII redactor (`services/ai_service.py`) that scrubs emails and phone numbers before sending data to Google Gemini.
* **Report immediately** if you find instances where PII is *not* being correctly redacted or is being logged in plain text.

### 3. Authorization & Access Control

* **Slack User Spoofing**: Bypassing checks that ensure commands (like `/evidently-nudge`) are only executed by authorised users.
* **Database Access**: Unauthorised reading or writing to the Supabase backend.

### 4. Credential Management

* **Token Exposure**: Any accidental logging or exposure of:
* `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN`
* `GOOGLE_API_KEY`
* `SUPABASE_KEY`
* `GOOGLE_SERVICE_ACCOUNT_JSON`



## Development Guidelines for Security

Contributors must adhere to these practices to maintain a secure codebase:

* **Secrets Management**: Never commit `.env` files. Ensure `.gitignore` is always respected. Use `os.environ` for all sensitive keys.
* **Logging**: Do not log full payloads of Slack events or AI responses in production. Use `logger.debug` for sensitive info only during local development.
* **Dependencies**: Periodically check `requirements.txt` for packages with known vulnerabilities.

## Response Timeline

* **Acknowledgment**: We will respond to your report within 48 hours.
* **Assessment**: We will assess the severity and impact within 5 business days.
* **Fix**: A patch will be deployed as soon as possible, depending on complexity.

Thank you for helping keep the Evidently Bot secure.
