import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is optional for deployed envs
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

if load_dotenv:
    load_dotenv(PROJECT_ROOT / ".env", encoding="utf-8-sig", override=True)


def _bool_env(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


APP_ENV = os.getenv("APP_ENV", "local")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
FLASK_DEBUG = _bool_env("FLASK_DEBUG", False)

# SQLite remains available as a local fallback. Supabase is the enterprise data
# layer once SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set.
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "smartqa.db"))

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_HTTP_PROXY = os.getenv("SUPABASE_HTTP_PROXY", "")
SUPABASE_HTTPS_PROXY = os.getenv("SUPABASE_HTTPS_PROXY", "")
SUPABASE_ENABLED = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
INTERNAL_AUTH_REQUIRED = _bool_env("INTERNAL_AUTH_REQUIRED", False)
CUSTOMER_ACCESS_TOKEN_SECRET = os.getenv("CUSTOMER_ACCESS_TOKEN_SECRET", SUPABASE_SERVICE_ROLE_KEY or "smartqa-local-customer-token")

DIFY_API_URL = os.getenv("DIFY_API_URL", "http://localhost/v1").rstrip("/")
DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
DIFY_USER = os.getenv("DIFY_USER", "smartqa-system")
DIFY_APP_MODE = os.getenv("DIFY_APP_MODE", "auto").strip().lower()
DIFY_ENABLED = bool(DIFY_API_KEY)
DIFY_DATASET_ID = os.getenv("DIFY_DATASET_ID", "")
DIFY_DATASET_API_KEY = os.getenv("DIFY_DATASET_API_KEY", DIFY_API_KEY)

WECOM_CORP_ID = os.getenv("WECOM_CORP_ID", "")
WECOM_AGENT_ID = os.getenv("WECOM_AGENT_ID", "")
WECOM_SECRET = os.getenv("WECOM_SECRET", "")
WECOM_KF_SECRET = os.getenv("WECOM_KF_SECRET", "")
WECOM_KF_OPEN_KFID = os.getenv("WECOM_KF_OPEN_KFID", "")
WECOM_TOKEN = os.getenv("WECOM_TOKEN", "")
WECOM_ENCODING_AES_KEY = os.getenv("WECOM_ENCODING_AES_KEY", "")
WECOM_PUBLIC_BASE_URL = os.getenv("WECOM_PUBLIC_BASE_URL", "").rstrip("/")
WECOM_ENABLED = bool(WECOM_CORP_ID and WECOM_AGENT_ID and WECOM_SECRET and WECOM_TOKEN)
WECOM_KF_ENABLED = bool(WECOM_CORP_ID and (WECOM_KF_SECRET or WECOM_SECRET) and WECOM_TOKEN)
WECOM_ENCRYPTION_ENABLED = bool(WECOM_ENCODING_AES_KEY)
WECOM_KF_POLL_ENABLED = _bool_env("WECOM_KF_POLL_ENABLED", False)
WECOM_KF_POLL_INTERVAL_SECONDS = int(os.getenv("WECOM_KF_POLL_INTERVAL_SECONDS", "15"))
WECOM_KF_IMMEDIATE_ACK_ENABLED = _bool_env("WECOM_KF_IMMEDIATE_ACK_ENABLED", True)
WECOM_KF_IMMEDIATE_ACK_TEXT = os.getenv(
    "WECOM_KF_IMMEDIATE_ACK_TEXT",
    "已收到，我正在查询产品资料和报价规则，请稍等。",
)
WECOM_KF_WELCOME_ENABLED = _bool_env("WECOM_KF_WELCOME_ENABLED", True)
WECOM_KF_WELCOME_TEXT = os.getenv(
    "WECOM_KF_WELCOME_TEXT",
    "您好，欢迎咨询鑫源保温防水防火批发。门店地址：天津市滨海新区厦门路环渤海建材市场L区33号，营业时间 7:30-18:30，销售电话：13512490668、13682003881。您也可以直接发送产品名称、规格、数量和项目地址，我会帮您查询产品参数、配送规则和报价前置条件；最终价格、库存和售后处理由人工同事确认。",
)
OPERATIONS_ALERTS_ENABLED = _bool_env("OPERATIONS_ALERTS_ENABLED", False)
OPERATIONS_ALERT_RECIPIENTS = os.getenv("OPERATIONS_ALERT_RECIPIENTS", "")
OPERATIONS_ALERT_MIN_SEVERITY = os.getenv("OPERATIONS_ALERT_MIN_SEVERITY", "warning")

MOCK_AI_ENABLED = _bool_env("MOCK_AI_ENABLED", not DIFY_ENABLED)
