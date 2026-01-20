HELP_HEADER = "📘 Evidently Instruction Manual"
HELP_WELCOME = "*Welcome to your AI Innovation Assistant.*"
HELP_SETUP = (
    "*1. Setup & Projects*\n"
    "Type `/evidently-status` to see your current project health. "
    "Go to the Home Tab to switch projects."
)
HELP_TOOLKIT = "*2. The Toolkit*\nType `/evidently-methods [stage]` (e.g., 'discovery') to get method cards."
HELP_INTERVIEW = "*3. Rapid Interviewing*\nType `/evidently-ask [method]` (e.g., '{default_method}') to get a script."
HELP_ANALYSIS = "*4. Analysis*\nReply to any thread with `@Evidently` to extract insights."

WELCOME_GREETING = "👋 *Thanks for adding me!* I'm Evidently, your AI innovation assistant."
WELCOME_USAGE = (
    "Here is how you can use me in this channel:\n\n"
    "🧵 *Analyse Threads:* Reply to any thread and mention `@Evidently` to extract hypotheses and evidence.\n"
    "⚡ *Shortcuts:* Click the `...` on any message → `Apps` → `Extract Insights`.\n"
    "🛠 *Toolkit:* Type `/evidently-methods` to get rapid suggestions for your current stage."
)

PUBLIC_HOLIDAYS = {
    "2025-01-01",
    "2025-12-25",
    "2025-12-26",
}

VALID_ASSUMPTION_CATEGORIES = ("Opportunity", "Capability", "Progress")
ASSUMPTION_DEFAULT_CATEGORY = VALID_ASSUMPTION_CATEGORIES[0]
LOW_CONFIDENCE_THRESHOLD = 3
