# Security Policy

## Supported Versions

We currently support the latest version of the main branch.

| Version | Supported          |
| ------- | ------------------ |
| Main    | :white_check_mark: |

## Reporting a Vulnerability

The **Nesta Evidently Bot** handles internal communication data and interfaces with external AI services (Google Gemini). We take security seriously.

**Do not open public GitHub issues for security vulnerabilities.**

If you have discovered a security vulnerability, please follow these steps:

1.  **Email**: Send a detailed report to the project maintainer (e.g., your-email@nesta.org.uk).
2.  **Encryption**: If possible, encrypt sensitive information.
3.  **Content**: Please include:
    * Type of issue (e.g., SQL injection, Cross-Site Scripting, Token Leakage).
    * Full paths of source files involved.
    * Step-by-step instructions to reproduce the issue.
    * Proof-of-concept or exploit code (if applicable).

### Critical Areas
We are particularly interested in reports regarding:
* **Prompt Injection**: Manipulation of the Gemini AI output to bypass safety filters or exfiltrate data.
* **Token Exposure**: Any logging or exposure of `SLACK_BOT_TOKEN`, `GOOGLE_API_KEY`, or database credentials.
* **Authorization**: Bypassing Slack user checks to access admin-only commands (e.g., `update_home_tab` for other users).

## Response Timeline

* **Acknowledgment**: We will respond to your report within 48 hours.
* **Assessment**: We will assess the severity and impact within 5 business days.
* **Fix**: A patch will be deployed as soon as possible, depending on complexity.

Thank you for helping keep the Evidently Bot secure.
