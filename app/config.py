import os
from dotenv import load_dotenv

load_dotenv()

# LLM / Groq Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "")

# Course Catalog File Path
COURSES_FILE = os.getenv(
    "COURSES_FILE",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "courses_data.xlsx"),
)
COURSE_PAGE_BASE_URL = os.getenv("COURSE_PAGE_BASE_URL", "")

# Chatbot Session Settings
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))
SESSION_EXPIRY_HOURS = int(os.getenv("SESSION_EXPIRY_HOURS", "24"))
LEAD_CAPTURE_TIMING = os.getenv("LEAD_CAPTURE_TIMING", "early").lower()

# Notification Providers
CALLMEBOT_PHONE = os.getenv("CALLMEBOT_PHONE", "")
CALLMEBOT_APIKEY = os.getenv("CALLMEBOT_APIKEY", "")
CRM_WEBHOOK_URL = os.getenv("CRM_WEBHOOK_URL", "")

# Environment & Security
TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
_origins_raw = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = [o.strip() for o in _origins_raw.split(",") if o.strip()]
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "90"))