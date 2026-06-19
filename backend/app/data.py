import json
from pathlib import Path
from typing import Dict, Any

from app.config import settings

DATA_DIR = settings.DATA_DIR

with open(DATA_DIR / "crm_database.json", encoding="utf-8") as f:
    CRM_DATA: Dict[str, Any] = json.load(f)

with open(DATA_DIR / "refund_policy.txt", encoding="utf-8") as f:
    REFUND_POLICY = f.read()

CUSTOMERS = {customer["id"]: customer for customer in CRM_DATA["customers"]}
EMAIL_INDEX = {
    customer["email"].lower(): customer["id"]
    for customer in CRM_DATA["customers"]
}
