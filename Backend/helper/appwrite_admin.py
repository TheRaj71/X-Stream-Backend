import base64
import hashlib
import hmac
import json
import re
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from appwrite.client import Client
from appwrite.exception import AppwriteException
from appwrite.id import ID
from appwrite.query import Query
from appwrite.services.account import Account
from appwrite.services.tables_db import TablesDB
from appwrite.services.users import Users

from Backend.config import Telegram


IST = ZoneInfo("Asia/Kolkata")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DURATION_RE = re.compile(
    r"^(?P<amount>\d+)\s*(?P<unit>m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)$",
    re.IGNORECASE,
)


class AppwriteAdminError(Exception):
    pass


@dataclass
class PremiumResult:
    user: Dict[str, Any]
    row: Dict[str, Any]
    expiry_date: datetime
    created_user: bool
    created_password: Optional[str] = None


@dataclass
class DeleteResult:
    email: str
    user_id: Optional[str]
    deleted_user: bool
    deleted_subscriptions: int
    deleted_watchlist_items: int


@dataclass
class MemberInfo:
    email: str
    user: Optional[Dict[str, Any]]
    subscriptions: List[Dict[str, Any]]
    watchlist_count: int
    stremio_token: Optional[str] = None


def validate_email(email: str) -> str:
    normalized = email.strip().lower()
    if not EMAIL_RE.match(normalized):
        raise AppwriteAdminError("Invalid email address.")
    return normalized


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def parse_expiry(value: str, now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    token = value.strip()
    match = DURATION_RE.match(token)

    if match:
        amount = int(match.group("amount"))
        unit = match.group("unit").lower()
        if amount <= 0:
            raise AppwriteAdminError("Duration must be greater than zero.")
        if unit.startswith("m"):
            return now + timedelta(minutes=amount)
        if unit.startswith("h"):
            return now + timedelta(hours=amount)
        return now + timedelta(days=amount)

    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", token):
            local_expiry = datetime.combine(datetime.fromisoformat(token).date(), time.max, tzinfo=IST)
            return local_expiry.astimezone(timezone.utc)

        parsed = datetime.fromisoformat(token.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=IST)
        return parsed.astimezone(timezone.utc)
    except ValueError as exc:
        raise AppwriteAdminError(
            "Invalid duration/date. Use examples like 30m, 12h, 7d, 2026-12-31, or 2026-12-31T23:59:59+05:30."
        ) from exc


def format_remaining_duration(expiry_value: Optional[str]) -> str:
    if not expiry_value:
        return "No expiry"

    try:
        expiry_date = datetime.fromisoformat(expiry_value.replace("Z", "+00:00"))
        if expiry_date.tzinfo is None:
            expiry_date = expiry_date.replace(tzinfo=timezone.utc)
    except ValueError:
        return "Invalid expiry date"

    delta = expiry_date.astimezone(timezone.utc) - datetime.now(timezone.utc)
    expired = delta.total_seconds() <= 0
    seconds = abs(int(delta.total_seconds()))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)

    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes or not parts:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

    text = ", ".join(parts[:3])
    return f"Expired {text} ago" if expired else text


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sdk_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "dict"):
        return value.dict()
    return dict(value)


class AppwriteAdmin:
    def __init__(self):
        missing = [
            name
            for name, value in {
                "APPWRITE_PROJECT_ID": Telegram.APPWRITE_PROJECT_ID,
                "APPWRITE_API_KEY": Telegram.APPWRITE_API_KEY,
            }.items()
            if not value
        ]
        if missing:
            raise AppwriteAdminError(f"Missing Appwrite config: {', '.join(missing)}")

        client = Client()
        client.set_endpoint(Telegram.APPWRITE_ENDPOINT)
        client.set_project(Telegram.APPWRITE_PROJECT_ID)
        client.set_key(Telegram.APPWRITE_API_KEY)

        self.users = Users(client)
        self.tables = TablesDB(client)
        self.database_id = Telegram.APPWRITE_DATABASE_ID
        self.subscriptions_table_id = Telegram.APPWRITE_SUBSCRIPTIONS_TABLE_ID
        self.watchlist_table_id = Telegram.APPWRITE_WATCHLIST_TABLE_ID

    def grant_premium(self, email: str, expiry_arg: str) -> PremiumResult:
        email = validate_email(email)
        expiry_date = parse_expiry(expiry_arg)
        user = self._get_user_by_email(email)
        created_user = False
        created_password = None

        if user is None:
            created_password = generate_password()
            user = _sdk_dict(self.users.create(
                user_id=ID.unique(),
                email=email,
                password=created_password,
                name=email.split("@", 1)[0],
            ))
            created_user = True

        now_iso = self._to_appwrite_datetime(datetime.now(timezone.utc))
        expiry_iso = self._to_appwrite_datetime(expiry_date)
        existing_row = self._first_subscription_row(user["$id"], email)
        row_data = {
            "userId": user["$id"],
            "email": email,
            "subscriptionType": "premium",
            "subscriptionStatus": "active",
            "startDate": now_iso,
            "expiryDate": expiry_iso,
            "isActive": True,
            "updatedAt": now_iso,
        }

        if existing_row:
            row = _sdk_dict(self.tables.update_row(
                database_id=self.database_id,
                table_id=self.subscriptions_table_id,
                row_id=existing_row["$id"],
                data=row_data,
            ))
        else:
            row = _sdk_dict(self.tables.create_row(
                database_id=self.database_id,
                table_id=self.subscriptions_table_id,
                row_id=user["$id"],
                data={**row_data, "createdAt": now_iso},
            ))

        return PremiumResult(
            user=user,
            row=row,
            expiry_date=expiry_date,
            created_user=created_user,
            created_password=created_password,
        )

    def get_user_from_jwt(self, jwt: str) -> Dict[str, Any]:
        jwt = (jwt or "").strip()
        if not jwt:
            raise AppwriteAdminError("Missing Appwrite JWT")

        client = Client()
        client.set_endpoint(Telegram.APPWRITE_ENDPOINT)
        client.set_project(Telegram.APPWRITE_PROJECT_ID)
        client.set_jwt(jwt)
        return _sdk_dict(Account(client).get())

    def create_stremio_token(self, user: Dict[str, Any]) -> str:
        secret = self._stremio_secret()
        payload = {
            "purpose": "stremio",
            "userId": user["$id"],
            "email": user["email"].lower(),
        }
        payload_part = _base64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        signature = hmac.new(secret.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()
        return f"{payload_part}.{_base64url_encode(signature)}"

    def verify_stremio_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            payload_part, signature_part = token.split(".", 1)
            expected = hmac.new(
                self._stremio_secret().encode("utf-8"),
                payload_part.encode("ascii"),
                hashlib.sha256,
            ).digest()
            provided = _base64url_decode(signature_part)
            if not hmac.compare_digest(expected, provided):
                return None

            payload = json.loads(_base64url_decode(payload_part).decode("utf-8"))
            if payload.get("purpose") != "stremio":
                return None

            email = validate_email(payload.get("email", ""))
            user_id = str(payload.get("userId") or "")
            user = self._get_user_by_email(email)
            if not user or user.get("$id") != user_id or user.get("status") is not True:
                return None

            if not self.has_active_subscription(user_id, email):
                return None

            return user
        except Exception:
            return None

    def has_active_subscription(self, user_id: str, email: str) -> bool:
        now = datetime.now(timezone.utc)
        for row in self._subscription_rows(user_id, email):
            if row.get("subscriptionStatus") != "active" or row.get("isActive") is not True:
                continue

            expiry_value = row.get("expiryDate")
            if not expiry_value:
                return True

            try:
                expiry_date = datetime.fromisoformat(str(expiry_value).replace("Z", "+00:00"))
                if expiry_date.tzinfo is None:
                    expiry_date = expiry_date.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            if expiry_date.astimezone(timezone.utc) > now:
                return True

        return False

    def delete_member(self, email: str) -> DeleteResult:
        email = validate_email(email)
        user = self._get_user_by_email(email)
        user_id = user["$id"] if user else None
        deleted_subscriptions = self._delete_matching_rows(
            self.subscriptions_table_id,
            self._subscription_queries(user_id, email),
        )
        deleted_watchlist_items = 0

        if user_id:
            deleted_watchlist_items = self._delete_matching_rows(
                self.watchlist_table_id,
                [[Query.equal("userId", user_id)]],
            )
            self.users.delete(user_id=user_id)

        return DeleteResult(
            email=email,
            user_id=user_id,
            deleted_user=user is not None,
            deleted_subscriptions=deleted_subscriptions,
            deleted_watchlist_items=deleted_watchlist_items,
        )

    def get_member_info(self, email: str) -> MemberInfo:
        email = validate_email(email)
        user = self._get_user_by_email(email)
        user_id = user["$id"] if user else None
        subscriptions = self._subscription_rows(user_id, email)
        watchlist_count = 0

        if user_id:
            watchlist_count = len(self._list_rows(self.watchlist_table_id, [Query.equal("userId", user_id)]))

        return MemberInfo(
            email=email,
            user=user,
            subscriptions=subscriptions,
            watchlist_count=watchlist_count,
            stremio_token=self.create_stremio_token(user) if user else None,
        )

    def _get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        users = _sdk_dict(self.users.list(search=email, queries=[Query.limit(25)])).get("users", [])
        users = [_sdk_dict(user) for user in users]
        return next((user for user in users if user.get("email", "").lower() == email), None)

    def _first_subscription_row(self, user_id: str, email: str) -> Optional[Dict[str, Any]]:
        rows = self._subscription_rows(user_id, email)
        return rows[0] if rows else None

    def _subscription_rows(self, user_id: Optional[str], email: str) -> List[Dict[str, Any]]:
        rows = []
        seen = set()
        for queries in self._subscription_queries(user_id, email):
            for row in self._list_rows(self.subscriptions_table_id, queries):
                row_id = row["$id"]
                if row_id in seen:
                    continue
                seen.add(row_id)
                rows.append(row)
        return rows

    def _subscription_queries(self, user_id: Optional[str], email: str) -> List[List[str]]:
        queries = [[Query.equal("email", email)]]
        if user_id:
            queries.insert(0, [Query.equal("userId", user_id)])
        return queries

    def _delete_matching_rows(self, table_id: str, query_sets: List[List[str]]) -> int:
        deleted = 0
        seen = set()
        for queries in query_sets:
            rows = self._list_rows(table_id, queries)
            for row in rows:
                row_id = row["$id"]
                if row_id in seen:
                    continue
                self.tables.delete_row(
                    database_id=self.database_id,
                    table_id=table_id,
                    row_id=row_id,
                )
                seen.add(row_id)
                deleted += 1
        return deleted

    def _list_rows(self, table_id: str, queries: List[str]) -> List[Dict[str, Any]]:
        rows = []
        offset = 0
        limit = 100
        while True:
            page = _sdk_dict(self.tables.list_rows(
                database_id=self.database_id,
                table_id=table_id,
                queries=[*queries, Query.limit(limit), Query.offset(offset)],
            ))
            batch = [_sdk_dict(row) for row in page.get("rows", [])]
            rows.extend(batch)
            if len(batch) < limit:
                return rows
            offset += limit

    @staticmethod
    def _to_appwrite_datetime(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @staticmethod
    def _stremio_secret() -> str:
        secret = Telegram.STREMIO_AUTH_SECRET or Telegram.APPWRITE_API_KEY
        if not secret:
            raise AppwriteAdminError("Missing STREMIO_AUTH_SECRET or APPWRITE_API_KEY")
        return secret


def describe_appwrite_error(error: Exception) -> str:
    if isinstance(error, AppwriteAdminError):
        return str(error)
    if isinstance(error, AppwriteException):
        message = getattr(error, "message", None) or str(error)
        code = getattr(error, "code", None)
        return f"Appwrite error{f' {code}' if code else ''}: {message}"
    return "Unexpected Appwrite admin error."
