from datetime import date, datetime, time, timedelta
import base64
import hashlib
from html import escape
import hmac
from io import BytesIO
import os
import re
import secrets

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy.exc import OperationalError

from database import Base, SessionLocal, engine
from models import (
    AccountCredential,
    CompetitionEvent,
    EventPermission,
    EventGroup,
    EventItem,
    EventLevel,
    LoginSession,
    Registration,
    SiteAsset,
    StaffMember,
    TeamUnit,
    UserProfile,
)


COMPONENT_DIR = os.path.join(os.path.dirname(__file__), "components", "zh_calendar")
zh_calendar_component = (
    components.declare_component("zh_calendar_component", path=COMPONENT_DIR)
    if os.path.isdir(COMPONENT_DIR)
    else None
)

def is_schema_race_error(error: Exception) -> bool:
    message = str(error).lower()
    return "already exists" in message or "duplicate table" in message or "duplicate index" in message


def create_database_tables() -> None:
    try:
        Base.metadata.create_all(bind=engine)
    except OperationalError as exc:
        if not is_schema_race_error(exc):
            raise
        for table in Base.metadata.sorted_tables:
            try:
                table.create(bind=engine, checkfirst=True)
            except OperationalError as table_exc:
                if not is_schema_race_error(table_exc):
                    raise


create_database_tables()

DEFAULT_ADMIN_USERNAME = "yec12395"
DEFAULT_ADMIN_PASSWORD_HASH = "pbkdf2_sha256$260000$dGtkLWVucm9sbC1hZG1pbi12MQ==$YnIoOx0L1Kc2PngOnBAnv8_NpeOalaRa0SvtRW8bEqQ="
PASSWORD_HASH_ITERATIONS = 260000
LOGIN_COOKIE_NAME = "tkd_enroll_session"
LOGIN_SESSION_DAYS = 14


def ensure_registration_schema() -> None:
    if engine.dialect.name != "sqlite":
        return

    required_columns = {
        "account_email": "VARCHAR",
        "leader_name": "VARCHAR",
        "manager_name": "VARCHAR",
        "birth_date": "VARCHAR",
        "group_name": "VARCHAR",
        "rank_level": "VARCHAR",
        "item_amount": "INTEGER",
        "note": "VARCHAR",
        "payment_status": "VARCHAR",
        "pay_five_digits": "VARCHAR",
        "pay_remark": "VARCHAR",
    }
    with engine.begin() as connection:
        existing_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(registrations)").fetchall()
        }
        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                try:
                    connection.exec_driver_sql(
                        f"ALTER TABLE registrations ADD COLUMN {column_name} {column_type}"
                    )
                except Exception:
                    pass

ensure_registration_schema()


def update_payment_info(account_email: str, event_name: str, five_digits: str, remark: str):
    db = SessionLocal()
    try:
        items = db.query(Registration).filter(
            Registration.account_email == account_email,
            Registration.event_name == event_name
        ).all()
        for item in items:
            item.pay_five_digits = five_digits
            item.pay_remark = remark
            item.payment_status = "待核對"
        db.commit()
    finally:
        db.close()

# 管理員一鍵確認收款
def admin_confirm_payment(event_name: str, team_name: str):
    db = SessionLocal()
    try:
        items = db.query(Registration).filter(
            Registration.event_name == event_name,
            Registration.team_name == team_name
        ).all()
        for item in items:
            item.payment_status = "已確認"
        db.commit()
    finally:
        db.close()


def ensure_user_profile_schema() -> None:
    if engine.dialect.name != "sqlite":
        return

    required_columns = {"role": "VARCHAR"}
    with engine.begin() as connection:
        existing_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(user_profiles)").fetchall()
        }
        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE user_profiles ADD COLUMN {column_name} {column_type}"
                )


ensure_user_profile_schema()


def ensure_event_schema() -> None:
    if engine.dialect.name != "sqlite":
        return

    required_columns = {
        "registration_start": "VARCHAR",
        "pdf_url": "VARCHAR",
    }
    with engine.begin() as connection:
        existing_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(competition_events)").fetchall()
        }
        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE competition_events ADD COLUMN {column_name} {column_type}"
                )


ensure_event_schema()


DEFAULT_SITE_NAME = "賽事報名網"
DEFAULT_SITE_TAGLINE = "跆拳道賽事報名平台"
SITE_NAME_SETTING_KEY = "site_name"


def initial_site_name() -> str:
    db = SessionLocal()
    try:
        asset = db.query(SiteAsset).filter(SiteAsset.asset_key == SITE_NAME_SETTING_KEY).first()
        if not asset or not asset.data_base64:
            return DEFAULT_SITE_NAME
        return base64.b64decode(asset.data_base64.encode("ascii")).decode("utf-8").strip() or DEFAULT_SITE_NAME
    except Exception:
        return DEFAULT_SITE_NAME
    finally:
        db.close()


st.set_page_config(
    page_title=initial_site_name(),
    page_icon="賽",
    layout="wide",
    initial_sidebar_state="expanded",
)


EVENTS = []
EVENT_CLEAR_MARKER = "events-cleared-2026-05-30"

CATEGORIES = {
    "對打": ["國小低年級", "國小中年級", "國小高年級", "國中組", "高中組", "社會組"],
    "品勢": ["個人男", "個人女", "雙人組", "團體組"],
    "競速踢擊": ["幼兒組", "國小組", "公開組"],
}

RANK_LEVELS = [
    "請選擇",
    "白帶",
    "黃帶",
    "綠帶",
    "藍帶",
    "紅帶",
    "黑帶一段",
    "黑帶二段",
    "黑帶三段以上",
    "公開組",
]

UNIT_PAGE = "單位資料"
LOGIN_PAGE = "登入介面"
ACCOUNT_PAGE = "帳號資料"
VISUAL_SETTINGS_PAGE = "視覺設定"
PAGE_ALIASES = {"個人與單位": UNIT_PAGE, "系統登入": LOGIN_PAGE}
NAV_PAGES = ["賽事列表", "我的報名", UNIT_PAGE, LOGIN_PAGE]
PAGES = NAV_PAGES + ["競賽規程", "線上報名", "管理後台", VISUAL_SETTINGS_PAGE, ACCOUNT_PAGE]
ADMIN_ONLY_PAGES = {"管理後台"}
SUPER_ADMIN_ONLY_PAGES = {VISUAL_SETTINGS_PAGE}
PROFILE_SECTIONS = ["參賽單位", "隊職員名單"]
PAGE_QUERY_VALUES = {
    "賽事列表": "events",
    "我的報名": "my",
    UNIT_PAGE: "profile",
    LOGIN_PAGE: "login",
    "競賽規程": "rules",
    "線上報名": "register",
    "管理後台": "admin",
    VISUAL_SETTINGS_PAGE: "visual",
    ACCOUNT_PAGE: "account",
}
QUERY_PAGE_VALUES = {
    "home": "賽事列表",
    "events": "賽事列表",
    "list": "賽事列表",
    "my": "我的報名",
    "registrations": "我的報名",
    "profile": UNIT_PAGE,
    "unit": UNIT_PAGE,
    "login": LOGIN_PAGE,
    "rules": "競賽規程",
    "register": "線上報名",
    "admin": "管理後台",
    "visual": VISUAL_SETTINGS_PAGE,
    "account": ACCOUNT_PAGE,
}

ROLE_SUPER_ADMIN = "super_admin"
ROLE_ORGANIZER = "organizer"
ROLE_REGISTRANT = "registrant"
ROLE_LEGACY_ADMIN = "admin"
ROLE_LEGACY_COACH = "coach"
ROLE_LABELS = {
    ROLE_SUPER_ADMIN: "最高管理員",
    ROLE_ORGANIZER: "主辦單位",
    ROLE_REGISTRANT: "報名人",
    ROLE_LEGACY_ADMIN: "最高管理員",
    ROLE_LEGACY_COACH: "報名人",
}
ROLE_OPTIONS = {
    "最高管理員": ROLE_SUPER_ADMIN,
    "主辦單位": ROLE_ORGANIZER,
    "報名人": ROLE_REGISTRANT,
}
REGISTRATION_COLUMNS = [
    "編號",
    "帳號",
    "賽事",
    "選手姓名",
    "報名單位",
    "領隊",
    "教練",
    "管理",
    "性別",
    "出生年月日",
    "項目",
    "組別",
    "級別",
    "金額",
    "繳費狀態",
    "匯款後五碼",
    "備註",
    "電話",
]


def parse_dateish(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_datetimeish(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%Y-%m-%d":
                return parsed.replace(hour=0, minute=0, second=0)
            return parsed
        except ValueError:
            continue
    return None


def format_datetime_value(value: str | None, fallback: datetime | None = None) -> str:
    parsed = parse_datetimeish(value)
    if parsed:
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    if fallback:
        return fallback.strftime("%Y-%m-%d %H:%M:%S")
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def combine_date_time(selected_date: date, selected_time: time, second: int = 0) -> str:
    return datetime.combine(selected_date, selected_time).replace(second=second).strftime("%Y-%m-%d %H:%M:%S")


def render_datetime_picker(label: str, default_value: datetime, key_prefix: str) -> str:
    if zh_calendar_component is None:
        selected_date = st.date_input(
            label,
            value=default_value.date(),
            key=f"{key_prefix}-date",
        )
        selected_time = st.time_input(
            f"{label}時間",
            value=time(default_value.hour, default_value.minute),
            step=timedelta(minutes=1),
            key=f"{key_prefix}-time",
        )
        return combine_date_time(selected_date, selected_time)

    value = default_value.strftime("%Y-%m-%d %H:%M")
    text_value = zh_calendar_component(
        mode="datetime",
        label=label,
        value=value,
        default=value,
        key=f"{key_prefix}-datetime",
    )
    parsed = parse_datetimeish(text_value)
    if not parsed:
        st.warning(f"{label} 請使用 YYYY-MM-DD HH:MM 格式。")
        return default_value.replace(second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    return parsed.replace(second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def render_date_range_picker(label: str, default_range: tuple[date, date], key_prefix: str) -> list[str]:
    start, end = default_range
    if zh_calendar_component is None:
        value = st.date_input(
            label,
            value=(start, end),
            key=f"{key_prefix}-range",
        )
        return dates_from_calendar_range(value)

    value = zh_calendar_component(
        mode="range",
        label=label,
        start=start.isoformat(),
        end=end.isoformat(),
        default={
            "start": start.isoformat(),
            "end": end.isoformat(),
            "dates": dates_from_calendar_range((start, end)),
        },
        key=f"{key_prefix}-range",
    )
    if isinstance(value, dict) and value.get("dates"):
        return value["dates"]
    return dates_from_calendar_range((start, end))


def render_date_picker(label: str, default_value: date, key_prefix: str) -> date:
    if zh_calendar_component is None:
        value = st.date_input(
            label,
            value=default_value,
            key=f"{key_prefix}-date",
        )
        return value if isinstance(value, date) else default_value

    value = zh_calendar_component(
        mode="date",
        label=label,
        value=default_value.isoformat(),
        default=default_value.isoformat(),
        key=f"{key_prefix}-date",
    )
    parsed = parse_dateish(value)
    return parsed or default_value


def calculate_event_status(registration_start: str | None, deadline: str | None) -> str:
    now = datetime.now()
    start = parse_datetimeish(registration_start)
    end = parse_datetimeish(deadline)
    if start and now < start:
        return "即將開放"
    if end and now > end:
        return "報名已截止"
    return "熱烈報名中"


def date_options(days: int = 730) -> list[str]:
    start = date.today()
    return [(start + timedelta(days=offset)).isoformat() for offset in range(days + 1)]


def dates_from_calendar_range(value) -> list[str]:
    if isinstance(value, date):
        return [value.isoformat()]
    if not value:
        return []
    selected = list(value)
    if len(selected) == 1:
        return [selected[0].isoformat()]
    start, end = sorted(selected[:2])
    days = (end - start).days
    return [(start + timedelta(days=offset)).isoformat() for offset in range(days + 1)]


def date_range_default(value: str | None) -> tuple[date, date]:
    parsed_dates = [parse_dateish(item) for item in split_event_dates(value)]
    parsed_dates = [item for item in parsed_dates if item is not None]
    if not parsed_dates:
        today = date.today()
        return today, today
    return min(parsed_dates), max(parsed_dates)


def split_event_dates(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.replace("、", "\n").replace(",", "\n").splitlines() if part.strip()]


def format_event_dates(value: str | None) -> str:
    dates = split_event_dates(value)
    return "、".join(dates) if dates else ""


def format_event_date_range(value: str | None) -> str:
    parsed_dates = [parse_dateish(item) for item in split_event_dates(value)]
    parsed_dates = sorted(item for item in parsed_dates if item is not None)
    if not parsed_dates:
        return format_event_dates(value)

    start = parsed_dates[0]
    end = parsed_dates[-1]
    if start == end:
        return start.isoformat()
    if start.year == end.year and start.month == end.month:
        return f"{start.isoformat()}~{end.day:02d}"
    if start.year == end.year:
        return f"{start.isoformat()}~{end.month:02d}-{end.day:02d}"
    return f"{start.isoformat()}~{end.isoformat()}"


def format_public_event_date(value: str | None) -> str:
    parsed_dates = [parse_dateish(item) for item in split_event_dates(value)]
    parsed_dates = sorted(item for item in parsed_dates if item is not None)
    if not parsed_dates:
        return format_event_dates(value)

    start = parsed_dates[0]
    end = parsed_dates[-1]
    if start == end:
        return f"{start.month}/{start.day}"
    if start.year == end.year and start.month == end.month:
        return f"{start.month}/{start.day}-{end.day}"
    if start.year == end.year:
        return f"{start.month}/{start.day}-{end.month}/{end.day}"
    return f"{start.year}/{start.month}/{start.day}-{end.year}/{end.month}/{end.day}"


def google_drive_pdf_embed_url(value: str | None) -> str:
    if not value:
        return ""
    text = value.strip()
    if "drive.google.com" in text and "/file/d/" in text:
        file_id = text.split("/file/d/", 1)[1].split("/", 1)[0]
        return f"https://drive.google.com/file/d/{file_id}/preview"
    if "drive.google.com" in text and "id=" in text:
        file_id = text.split("id=", 1)[1].split("&", 1)[0]
        return f"https://drive.google.com/file/d/{file_id}/preview"
    if text.startswith("http"):
        return text
    return f"https://drive.google.com/file/d/{text}/preview"


def seed_default_events() -> None:
    db = SessionLocal()
    try:
        if not EVENTS:
            return
        if db.query(CompetitionEvent).count() > 0:
            return

        for event in EVENTS:
            db_event = CompetitionEvent(
                name=event["name"],
                city=event["city"],
                status=event["status"],
                registration_start=date.today().isoformat(),
                date=event["date"],
                deadline=event["deadline"],
                venue=event["venue"],
                host=event["host"],
                description=event["description"],
                pdf_url="",
            )
            db.add(db_event)
            db.flush()

            for item_name, groups in CATEGORIES.items():
                db_item = EventItem(event_id=db_event.id, name=item_name, amount=event["fee"])
                db.add(db_item)
                db.flush()
                for group_name in groups:
                    db_group = EventGroup(item_id=db_item.id, name=group_name)
                    db.add(db_group)
                    db.flush()
                    for level_name in RANK_LEVELS[1:]:
                        db.add(EventLevel(group_id=db_group.id, name=level_name))
        db.commit()
    finally:
        db.close()


seed_default_events()


def clear_existing_events_once() -> None:
    db = SessionLocal()
    try:
        if db.query(SiteAsset).filter(SiteAsset.asset_key == EVENT_CLEAR_MARKER).first():
            return

        db.query(EventPermission).delete(synchronize_session=False)
        db.query(EventLevel).delete(synchronize_session=False)
        db.query(EventGroup).delete(synchronize_session=False)
        db.query(EventItem).delete(synchronize_session=False)
        db.query(CompetitionEvent).delete(synchronize_session=False)
        db.add(
            SiteAsset(
                asset_key=EVENT_CLEAR_MARKER,
                filename="event-clear-marker",
                content_type="text/plain",
                data_base64="done",
            )
        )
        db.commit()
    finally:
        db.close()


clear_existing_events_once()


def event_to_dict(event: CompetitionEvent, amount: int = 0) -> dict:
    return {
        "id": event.id,
        "name": event.name,
        "city": event.city or "",
        "status": calculate_event_status(getattr(event, "registration_start", "") or "", event.deadline or ""),
        "registration_start": getattr(event, "registration_start", "") or "",
        "date": format_event_dates(event.date or ""),
        "date_raw": event.date or "",
        "deadline": event.deadline or "",
        "venue": event.venue or "",
        "host": event.host or "",
        "fee": amount,
        "description": event.description or "",
        "pdf_url": getattr(event, "pdf_url", "") or "",
    }


def get_events() -> list[dict]:
    db = SessionLocal()
    try:
        events = db.query(CompetitionEvent).order_by(CompetitionEvent.id.desc()).all()
        results = []
        for event in events:
            amounts = [
                item.amount or 0
                for item in db.query(EventItem).filter(EventItem.event_id == event.id).all()
                if item.amount is not None
            ]
            amount = min(amounts) if amounts else 0
            results.append(event_to_dict(event, amount))
        return results
    finally:
        db.close()


def get_event(event_name: str | None) -> dict | None:
    if not event_name:
        return None
    db = SessionLocal()
    try:
        event = db.query(CompetitionEvent).filter(CompetitionEvent.name == event_name).first()
        if event is None:
            return None
        amounts = [
            item.amount or 0
            for item in db.query(EventItem).filter(EventItem.event_id == event.id).all()
            if item.amount is not None
        ]
        return event_to_dict(event, min(amounts) if amounts else 0)
    finally:
        db.close()


def get_event_items(event_name: str) -> list[EventItem]:
    event = get_event(event_name)
    if not event:
        return []
    db = SessionLocal()
    try:
        return db.query(EventItem).filter(EventItem.event_id == event["id"]).order_by(EventItem.id.asc()).all()
    finally:
        db.close()


def get_event_groups(item_id: int) -> list[EventGroup]:
    db = SessionLocal()
    try:
        return db.query(EventGroup).filter(EventGroup.item_id == item_id).order_by(EventGroup.id.asc()).all()
    finally:
        db.close()


def get_event_levels(group_id: int) -> list[EventLevel]:
    db = SessionLocal()
    try:
        return db.query(EventLevel).filter(EventLevel.group_id == group_id).order_by(EventLevel.id.asc()).all()
    finally:
        db.close()


def notice_key(event_name: str) -> str:
    return f"notice_confirmed::{event_name}"


def notices_confirmed(event_name: str) -> bool:
    return (
        st.session_state.get(notice_key(event_name), False)
        or (
            st.session_state.get(f"privacy-confirmed-{event_name}", False)
            and st.session_state.get(f"safety-confirmed-{event_name}", False)
        )
    )


def open_event_detail(event_name: str) -> None:
    st.session_state["selected_event_name"] = event_name
    st.session_state["rules_event"] = event_name
    request_page_change("競賽規程")


def route_to_registration_or_unit_setup(event_name: str | None = None) -> None:
    if event_name:
        st.session_state["selected_event_name"] = event_name

    account = current_account()
    if account and not get_team_units(account):
        st.session_state["profile_section"] = "參賽單位"
        st.session_state["unit_setup_after_registration"] = True
        request_page_change(UNIT_PAGE)
        return

    st.session_state.pop("unit_setup_after_registration", None)
    request_page_change("線上報名")


def start_registration(event_name: str) -> None:
    st.session_state[notice_key(event_name)] = True
    route_to_registration_or_unit_setup(event_name)


def query_param_value(key: str) -> str | None:
    try:
        value = st.query_params.get(key)
    except Exception:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return value


def set_query_page(page: str) -> None:
    query_value = PAGE_QUERY_VALUES.get(PAGE_ALIASES.get(page, page))
    if not query_value:
        return
    try:
        st.query_params["page"] = query_value
        st.session_state["query_page_seen"] = query_value
    except Exception:
        pass


def apply_query_page() -> None:
    query_page = query_param_value("page")
    if not query_page:
        return
    query_page = query_page.strip().lower()
    page = QUERY_PAGE_VALUES.get(query_page)
    if not page or st.session_state.get("query_page_seen") == query_page:
        return
    st.session_state["query_page_seen"] = query_page
    request_page_change(page, update_query=False)


def request_page_change(page: str, update_query: bool = True) -> None:
    page = PAGE_ALIASES.get(page, page)
    st.session_state["pending_page"] = page
    if page in NAV_PAGES:
        st.session_state["nav_page"] = page
    if update_query:
        set_query_page(page)


def apply_pending_page_change() -> None:
    page = st.session_state.pop("pending_page", None)
    page = PAGE_ALIASES.get(page, page)
    if page in PAGES:
        st.session_state["page"] = page
        if page in NAV_PAGES:
            st.session_state["nav_page"] = page


def go_to_registration_page() -> None:
    route_to_registration_or_unit_setup()


def go_to_profile_page() -> None:
    request_page_change(UNIT_PAGE)


def go_home() -> None:
    st.session_state["page"] = "賽事列表"
    st.session_state["nav_page"] = "賽事列表"
    st.session_state.pop("pending_page", None)
    set_query_page("賽事列表")


def go_to_account_page() -> None:
    request_page_change(ACCOUNT_PAGE)


def go_to_login_page() -> None:
    request_page_change(LOGIN_PAGE)


def go_to_admin_page() -> None:
    request_page_change("管理後台")


def go_to_visual_settings_page() -> None:
    request_page_change(VISUAL_SETTINGS_PAGE)


def select_nav_page() -> None:
    st.session_state["page"] = st.session_state["nav_page"]
    st.session_state.pop("pending_page", None)
    set_query_page(st.session_state["page"])


def brand_logo_path() -> str | None:
    base_dir = os.path.dirname(__file__)
    for relative_path in (
        os.path.join("assets", "logo.png"),
        os.path.join("assets", "logo.jpg"),
        os.path.join("assets", "logo.jpeg"),
        os.path.join("assets", "logo.webp"),
        os.path.join("assets", "logo.svg"),
        "logo.png",
        "logo.jpg",
        "logo.jpeg",
        "logo.webp",
        "logo.svg",
    ):
        candidate = os.path.join(base_dir, relative_path)
        if os.path.exists(candidate):
            return candidate
    return None


IMAGE_UPLOAD_TYPES = ["png", "jpg", "jpeg", "webp", "svg"]


def uploaded_image_content_type(uploaded_file) -> str:
    if uploaded_file.type and uploaded_file.type.startswith("image/"):
        return uploaded_file.type
    extension = os.path.splitext(uploaded_file.name.lower())[1].lstrip(".")
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "svg": "image/svg+xml",
    }.get(extension, "application/octet-stream")


def get_site_asset(asset_key: str) -> dict | None:
    db = SessionLocal()
    try:
        asset = db.query(SiteAsset).filter(SiteAsset.asset_key == asset_key).first()
        if asset is None:
            return None
        return {
            "filename": asset.filename or "",
            "content_type": asset.content_type or "image/png",
            "data_base64": asset.data_base64 or "",
        }
    finally:
        db.close()


def site_asset_data_uri(asset_key: str) -> str | None:
    asset = get_site_asset(asset_key)
    if not asset or not asset["data_base64"]:
        return None
    return f"data:{asset['content_type']};base64,{asset['data_base64']}"


def save_site_asset(asset_key: str, uploaded_file) -> None:
    encoded_data = base64.b64encode(uploaded_file.getvalue()).decode("ascii")
    db = SessionLocal()
    try:
        asset = db.query(SiteAsset).filter(SiteAsset.asset_key == asset_key).first()
        if asset is None:
            asset = SiteAsset(asset_key=asset_key)
            db.add(asset)
        asset.filename = uploaded_file.name
        asset.content_type = uploaded_image_content_type(uploaded_file)
        asset.data_base64 = encoded_data
        db.commit()
    finally:
        db.close()


def delete_site_asset(asset_key: str) -> None:
    db = SessionLocal()
    try:
        asset = db.query(SiteAsset).filter(SiteAsset.asset_key == asset_key).first()
        if asset is not None:
            db.delete(asset)
            db.commit()
    finally:
        db.close()


def get_site_setting(setting_key: str, default: str = "") -> str:
    asset = get_site_asset(setting_key)
    if not asset or not asset["data_base64"]:
        return default
    try:
        return base64.b64decode(asset["data_base64"].encode("ascii")).decode("utf-8").strip() or default
    except Exception:
        return default


def save_site_setting(setting_key: str, value: str) -> None:
    encoded_data = base64.b64encode(value.strip().encode("utf-8")).decode("ascii")
    db = SessionLocal()
    try:
        asset = db.query(SiteAsset).filter(SiteAsset.asset_key == setting_key).first()
        if asset is None:
            asset = SiteAsset(asset_key=setting_key)
            db.add(asset)
        asset.filename = "site-setting"
        asset.content_type = "text/plain; charset=utf-8"
        asset.data_base64 = encoded_data
        db.commit()
    finally:
        db.close()


def site_name() -> str:
    return get_site_setting(SITE_NAME_SETTING_KEY, DEFAULT_SITE_NAME)


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --brand: #c8202f;
            --brand-dark: #8f1722;
            --navy: #17324d;
            --teal: #0f766e;
            --gold: #b7791f;
            --ink: #17202a;
            --muted: #647184;
            --line: #e3e7ed;
            --panel: #ffffff;
            --surface: #f5f6f8;
            --soft: #fff5f5;
            --shadow: 0 14px 34px rgba(22, 32, 42, .08);
        }

        .stApp {
            background: var(--surface);
            color: var(--ink);
        }

        html,
        body,
        [class*="css"] {
            font-family: "Inter", "Noto Sans TC", "Microsoft JhengHei", Arial, sans-serif;
        }

        [data-testid="stSidebar"] {
            background: #ffffff;
            border-right: 1px solid var(--line);
            box-shadow: 8px 0 30px rgba(22, 32, 42, .05);
        }

        [data-testid="stSidebar"] * {
            color: var(--ink) !important;
        }

        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: var(--brand) !important;
        }

        [data-testid="stSidebar"] .stRadio > label {
            font-weight: 700;
        }

        [data-testid="stSidebar"] div[role="radiogroup"] label {
            padding: .55rem .65rem;
        }

        [data-testid="stSidebar"] div[role="radiogroup"] label p {
            font-size: 1.08rem !important;
            font-weight: 850 !important;
        }

        [data-testid="stSidebar"] label:has(input:checked) {
            border-radius: 8px;
            background: var(--soft);
            border: 1px solid rgba(200, 32, 47, .22);
        }

        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
            color: var(--muted) !important;
        }

        .block-container {
            padding-top: 1rem;
            padding-bottom: 3rem;
            max-width: 1220px;
        }

        .sidebar-brand {
            display: flex;
            align-items: center;
            gap: .75rem;
            padding: .85rem .2rem 1rem;
        }

        .sidebar-logo {
            display: block;
            max-width: 96px;
            max-height: 96px;
            object-fit: contain;
            margin: .85rem 0 .4rem;
        }

        .brand-mark {
            display: grid;
            place-items: center;
            width: 44px;
            height: 44px;
            border-radius: 8px;
            background: var(--brand);
            color: #fff !important;
            font-weight: 900;
            letter-spacing: 0;
        }

        .sidebar-brand strong {
            display: block;
            color: var(--navy) !important;
            font-size: 1.05rem;
            line-height: 1.1;
        }

        .sidebar-brand span {
            display: block;
            color: var(--muted) !important;
            font-size: .82rem;
        }

        .login-panel {
            display: grid;
            gap: 1.1rem;
            max-width: 760px;
            margin: 0 auto 1.25rem;
            padding: 1.65rem;
            border: 1px solid var(--line);
            border-left: 5px solid var(--brand);
            border-radius: 8px;
            background: #ffffff;
            box-shadow: var(--shadow);
        }

        .login-panel h2 {
            margin: 0;
            color: var(--navy);
            font-size: 1.8rem;
            line-height: 1.25;
        }

        .login-panel p {
            margin: 0;
            color: var(--ink);
            line-height: 1.75;
        }

        .login-browser-note {
            padding: .9rem 1rem;
            border: 1px solid #f1d6a4;
            border-radius: 8px;
            background: #fffaf0;
            color: #815c13;
            line-height: 1.75;
        }

        .login-actions {
            display: grid;
            grid-template-columns: 1.1fr .9fr;
            gap: .75rem;
            align-items: stretch;
        }

        .hero {
            position: relative;
            overflow: hidden;
            border: 1px solid rgba(23, 50, 77, .2);
            border-radius: 8px;
            padding: 2.25rem;
            min-height: 300px;
            background:
                linear-gradient(90deg, rgba(13, 24, 38, .92) 0%, rgba(23, 50, 77, .76) 52%, rgba(200, 32, 47, .62) 100%),
                url("https://images.unsplash.com/photo-1555597408-26bc8e548a46?auto=format&fit=crop&w=1800&q=80");
            background-size: cover;
            background-position: center;
            color: white;
            box-shadow: var(--shadow);
        }

        .hero h1 {
            margin: .85rem 0 0;
            max-width: 760px;
            font-size: clamp(2rem, 4vw, 4rem);
            line-height: 1.05;
            letter-spacing: 0;
        }

        .hero p {
            margin: .9rem 0 0;
            max-width: 720px;
            font-size: 1.05rem;
            color: rgba(255, 255, 255, .88);
        }

        .hero-stats,
        .card-grid,
        .metric-grid,
        .summary-strip {
            display: grid;
            gap: .9rem;
        }

        .hero-stats {
            grid-template-columns: repeat(3, minmax(0, 1fr));
            max-width: 720px;
            margin-top: 1.6rem;
        }

        .stat,
        .event-card,
        .info-panel,
        .summary-card {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: rgba(255, 255, 255, .96);
        }

        .stat {
            padding: .9rem 1rem;
            color: var(--ink);
        }

        .stat strong {
            display: block;
            font-size: 1.45rem;
            color: var(--brand);
        }

        .stat span {
            color: var(--muted);
            font-size: .88rem;
        }

        .section-title {
            margin: 1.9rem 0 .8rem;
            padding-left: .75rem;
            border-left: 4px solid var(--brand);
            font-size: 1.45rem;
            font-weight: 800;
            color: var(--navy);
            letter-spacing: 0;
        }

        .card-grid {
            grid-template-columns: repeat(3, minmax(0, 1fr));
        }

        .event-card {
            position: relative;
            padding: 1.15rem;
            min-height: 214px;
            box-shadow: var(--shadow);
            border-top: 4px solid var(--brand);
        }

        .event-card h3 {
            margin: .95rem 0 .8rem;
            color: var(--navy);
            font-size: 1.42rem;
            line-height: 1.28;
        }

        .event-card p {
            margin: .45rem 0;
            color: var(--muted);
        }

        .event-description {
            min-height: 3.2rem;
        }

        .event-meta {
            display: grid;
            gap: .35rem;
            margin-top: 1rem;
            padding-top: .85rem;
            border-top: 1px solid var(--line);
        }

        .event-meta div {
            display: flex;
            justify-content: space-between;
            gap: .75rem;
            font-size: .92rem;
            color: var(--muted);
        }

        .event-meta strong {
            color: var(--ink);
        }

        .badge {
            display: inline-flex;
            align-items: center;
            padding: .28rem .62rem;
            border-radius: 999px;
            font-size: .78rem;
            font-weight: 800;
            color: #ffffff;
            background: var(--navy);
        }

        .badge.hot { background: var(--brand); }
        .badge.soon { background: var(--gold); }
        .badge.closed { background: #5f6c75; }

        .info-panel {
            padding: 1.15rem;
            box-shadow: var(--shadow);
            border-left: 4px solid var(--brand);
        }

        .info-panel h3 {
            margin-top: 0;
            color: var(--navy);
        }

        .small-note {
            color: var(--muted);
            font-size: .92rem;
        }

        .summary-strip {
            grid-template-columns: repeat(3, minmax(0, 1fr));
            margin: 1rem 0 .5rem;
        }

        .summary-card {
            padding: 1rem;
            box-shadow: 0 8px 22px rgba(22, 32, 42, .05);
        }

        .summary-card span {
            display: block;
            color: var(--muted);
            font-size: .85rem;
        }

        .summary-card strong {
            display: block;
            margin-top: .25rem;
            color: var(--navy);
            font-size: 1.45rem;
        }

        h1, h2, h3, h4 {
            color: var(--navy);
            letter-spacing: 0;
        }

        [data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: .85rem 1rem;
            box-shadow: 0 8px 22px rgba(22, 32, 42, .05);
        }

        [data-testid="stForm"] {
            background: #ffffff;
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 1rem;
            box-shadow: 0 8px 22px rgba(22, 32, 42, .04);
        }

        [data-baseweb="input"],
        [data-baseweb="select"],
        [data-baseweb="textarea"],
        textarea {
            border-radius: 8px;
        }

        [data-testid="stDataFrame"] {
            border: 1px solid var(--line);
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 8px 22px rgba(22, 32, 42, .04);
        }

        [data-testid="stAlert"] {
            border-radius: 8px;
            border: 1px solid var(--line);
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: .35rem;
            border-bottom: 1px solid var(--line);
        }

        .stTabs [data-baseweb="tab"] {
            border-radius: 8px 8px 0 0;
            padding: .65rem 1rem;
            font-weight: 800;
        }

        .stTabs [aria-selected="true"] {
            color: var(--brand) !important;
            border-bottom: 3px solid var(--brand);
            background: #ffffff;
        }

        .stButton > button,
        .stDownloadButton > button,
        [data-testid="stFormSubmitButton"] button {
            border-radius: 8px;
            border: 1px solid var(--brand);
            background: var(--brand);
            color: #ffffff;
            font-weight: 800;
            min-height: 2.55rem;
            box-shadow: 0 8px 18px rgba(200, 32, 47, .18);
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover,
        [data-testid="stFormSubmitButton"] button:hover {
            border-color: var(--brand-dark);
            background: var(--brand-dark);
            color: #ffffff;
        }

        .stButton > button:disabled,
        .stDownloadButton > button:disabled,
        [data-testid="stFormSubmitButton"] button:disabled {
            background: #e3e7ed;
            border-color: #d8dee8;
            color: #8b97a6;
            box-shadow: none;
        }

        div[data-testid="stExpander"] {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: #ffffff;
            box-shadow: 0 8px 22px rgba(22, 32, 42, .04);
        }

        .hierarchy-leaf {
            min-height: 2.55rem;
            display: flex;
            align-items: center;
            padding: .45rem .8rem;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: #ffffff;
            color: var(--ink);
            font-weight: 700;
        }

        .hierarchy-node {
            min-height: 2.55rem;
            display: flex;
            align-items: center;
            gap: .55rem;
            padding: .55rem .85rem;
            border: 1px solid var(--node-border);
            border-left: 6px solid var(--node-accent);
            border-radius: 8px;
            background: var(--node-bg);
            color: var(--node-fg);
            box-shadow: 0 8px 18px rgba(22, 32, 42, .08);
        }

        .hierarchy-node strong,
        .hierarchy-node span {
            color: inherit;
        }

        .hierarchy-node strong {
            font-weight: 900;
        }

        .hierarchy-node .hierarchy-kind {
            font-size: .78rem;
            font-weight: 900;
            opacity: .78;
        }

        .hierarchy-node .hierarchy-caret {
            font-weight: 900;
            opacity: .9;
        }

        .hierarchy-node .hierarchy-meta {
            margin-left: auto;
            font-size: .86rem;
            font-weight: 800;
            opacity: .86;
        }

        .hierarchy-node-group {
            border-left-width: 5px;
            box-shadow: 0 6px 14px rgba(22, 32, 42, .05);
        }

        .hierarchy-node-level {
            min-height: 2.35rem;
            border-left-width: 4px;
            box-shadow: none;
        }

        .hierarchy-empty {
            margin: .35rem 0 .7rem;
            padding: .75rem .9rem;
            border: 1px dashed #d7dce4;
            border-radius: 8px;
            background: #fafbfc;
            color: var(--muted);
        }

        hr {
            margin: 1.5rem 0;
            border-color: var(--line);
        }

        @media (max-width: 900px) {
            .hero {
                padding: 1.25rem;
                min-height: 260px;
            }

            .hero-stats,
            .card-grid,
            .summary-strip,
            .login-actions {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    background_uri = site_asset_data_uri("site_background")
    if background_uri:
        st.markdown(
            f"""
            <style>
            .hero {{
                background:
                    linear-gradient(90deg, rgba(13, 24, 38, .92) 0%, rgba(23, 50, 77, .76) 52%, rgba(200, 32, 47, .62) 100%),
                    url("{background_uri}");
                background-size: cover;
                background-position: center;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )


def db_to_dataframe(
    account_email: str | None = None,
    include_all: bool = False,
    event_names: list[str] | None = None,
) -> pd.DataFrame:
    db = SessionLocal()
    try:
        query = db.query(Registration)
        if include_all and event_names is not None:
            if not event_names:
                return pd.DataFrame(columns=REGISTRATION_COLUMNS)
            query = query.filter(Registration.event_name.in_(event_names))
        elif account_email and not include_all:
            query = query.filter(Registration.account_email == account_email)
        registrations = query.order_by(Registration.id.desc()).all()
        rows = [
            {
                "編號": item.id,
                "帳號": getattr(item, "account_email", "") or "",
                "賽事": item.event_name,
                "選手姓名": item.athlete_name,
                "報名單位": item.team_name,
                "領隊": getattr(item, "leader_name", "") or "",
                "教練": item.coach_name,
                "管理": getattr(item, "manager_name", "") or "",
                "性別": item.gender,
                "出生年月日": getattr(item, "birth_date", "") or "",
                "項目": item.category,
                "組別": getattr(item, "group_name", "") or item.level,
                "級別": getattr(item, "rank_level", "") or "",
                "金額": getattr(item, "item_amount", 0) or 0,
                "繳費狀態": getattr(item, "payment_status", "未繳費") or "未繳費",
                "匯款後五碼": getattr(item, "pay_five_digits", "") or "",
                "備註": getattr(item, "note", "") or "",
                "電話": item.phone,
            }
            for item in registrations
        ]
        return pd.DataFrame(rows, columns=REGISTRATION_COLUMNS)
    finally:
        db.close()


def dataframe_to_excel(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="報名名單")
    return buffer.getvalue()


def current_account() -> str | None:
    return st.session_state.get("account")


def normalize_role(role: str | None) -> str:
    if role == ROLE_LEGACY_ADMIN:
        return ROLE_SUPER_ADMIN
    if role == ROLE_LEGACY_COACH or not role:
        return ROLE_REGISTRANT
    if role in {ROLE_SUPER_ADMIN, ROLE_ORGANIZER, ROLE_REGISTRANT}:
        return role
    return ROLE_REGISTRANT


def role_label(role: str | None) -> str:
    return ROLE_LABELS.get(normalize_role(role), "報名人")


def current_role() -> str:
    account = current_account()
    profile = get_user_profile(account)
    return normalize_role(profile.role if profile else None)


def is_admin() -> bool:
    return current_role() == ROLE_SUPER_ADMIN


def is_organizer() -> bool:
    return current_role() == ROLE_ORGANIZER


def can_access_admin_backend() -> bool:
    return current_role() in {ROLE_SUPER_ADMIN, ROLE_ORGANIZER}


def visible_pages() -> list[str]:
    return NAV_PAGES


def can_access_page(page: str) -> bool:
    if page in SUPER_ADMIN_ONLY_PAGES:
        return is_admin()
    return page not in ADMIN_ONLY_PAGES or can_access_admin_backend()


def enforce_page_access(page: str) -> str:
    if can_access_page(page):
        return page

    st.session_state["page"] = "賽事列表"
    st.session_state.pop("pending_page", None)
    st.warning("此頁面權限不足，已為你切回賽事列表。")
    return "賽事列表"


def read_secret(*keys):
    try:
        value = st.secrets
        for key in keys:
            value = value[key]
        return value
    except Exception:
        return None


def normalize_username(username: str | None) -> str:
    return (username or "").strip().lower()


def validate_username(username: str) -> str | None:
    if not username:
        return "請輸入帳號。"
    if len(username) < 3 or len(username) > 50:
        return "帳號長度需為 3 到 50 個字元。"
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", username):
        return "帳號只能使用英文字母、數字、底線、橫線、點或 @。"
    return None


def encode_password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return (
        f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}$"
        f"{base64.urlsafe_b64encode(salt).decode('ascii')}$"
        f"{base64.urlsafe_b64encode(digest).decode('ascii')}"
    )


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        algorithm, iterations, salt_text, digest_text = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def get_account_credential(username: str | None) -> AccountCredential | None:
    normalized = normalize_username(username)
    if not normalized:
        return None
    db = SessionLocal()
    try:
        return db.query(AccountCredential).filter(AccountCredential.username == normalized).first()
    finally:
        db.close()


def account_credential_exists(username: str | None) -> bool:
    return get_account_credential(username) is not None


def create_password_account(username: str, password: str, role: str = ROLE_REGISTRANT) -> tuple[bool, str]:
    normalized = normalize_username(username)
    username_error = validate_username(normalized)
    if username_error:
        return False, username_error
    if len(password) < 6:
        return False, "密碼至少需要 6 個字元。"

    db = SessionLocal()
    try:
        if db.query(AccountCredential).filter(AccountCredential.username == normalized).first():
            return False, "此帳號已存在。"
        normalized_role = normalize_role(role)
        db.add(
            AccountCredential(
                username=normalized,
                password_hash=encode_password_hash(password),
                role=normalized_role,
            )
        )
        profile = db.query(UserProfile).filter(UserProfile.account_email == normalized).first()
        if profile is None:
            profile = UserProfile(account_email=normalized, role=normalized_role)
            db.add(profile)
        else:
            profile.role = normalized_role if normalized_role == ROLE_SUPER_ADMIN else normalize_role(profile.role)
        db.commit()
        return True, "帳號已建立。"
    finally:
        db.close()


def ensure_default_admin_credentials() -> None:
    admin_username = normalize_username(
        read_secret("ADMIN_USERNAME") or os.getenv("ADMIN_USERNAME") or DEFAULT_ADMIN_USERNAME
    )
    password_override = read_secret("ADMIN_PASSWORD") or os.getenv("ADMIN_PASSWORD")
    password_hash = encode_password_hash(str(password_override)) if password_override else DEFAULT_ADMIN_PASSWORD_HASH

    db = SessionLocal()
    try:
        credential = db.query(AccountCredential).filter(AccountCredential.username == admin_username).first()
        if credential is None:
            credential = AccountCredential(
                username=admin_username,
                password_hash=password_hash,
                role=ROLE_SUPER_ADMIN,
            )
            db.add(credential)
        else:
            credential.role = ROLE_SUPER_ADMIN
            if password_override:
                credential.password_hash = password_hash

        profile = db.query(UserProfile).filter(UserProfile.account_email == admin_username).first()
        if profile is None:
            profile = UserProfile(account_email=admin_username, role=ROLE_SUPER_ADMIN)
            db.add(profile)
        else:
            profile.role = ROLE_SUPER_ADMIN
        db.commit()
    finally:
        db.close()


def hash_login_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def login_session_expiry() -> datetime:
    return datetime.utcnow() + timedelta(days=LOGIN_SESSION_DAYS)


def create_login_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = login_session_expiry().strftime("%Y-%m-%d %H:%M:%S")
    now_text = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db = SessionLocal()
    try:
        db.query(LoginSession).filter(LoginSession.expires_at < now_text).delete(synchronize_session=False)
        db.add(
            LoginSession(
                username=username,
                token_hash=hash_login_token(token),
                expires_at=expires_at,
            )
        )
        db.commit()
    finally:
        db.close()
    return token


def login_session_username(token: str | None) -> str | None:
    if not token:
        return None
    now_text = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db = SessionLocal()
    try:
        session = db.query(LoginSession).filter(LoginSession.token_hash == hash_login_token(token)).first()
        if session is None or not session.expires_at or session.expires_at < now_text:
            return None
        return session.username
    finally:
        db.close()


def revoke_login_session(token: str | None) -> None:
    if not token:
        return
    db = SessionLocal()
    try:
        db.query(LoginSession).filter(LoginSession.token_hash == hash_login_token(token)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def browser_cookie_token() -> str:
    try:
        return str(st.context.cookies.get(LOGIN_COOKIE_NAME, "") or "")
    except Exception:
        return ""


def cookie_secure_suffix() -> str:
    try:
        return "; Secure" if str(st.context.url).startswith("https://") else ""
    except Exception:
        return ""


def render_login_cookie_scripts() -> bool:
    if st.session_state.pop("clear_login_cookie", False):
        components.html(
            f"""
            <script>
            document.cookie = "{LOGIN_COOKIE_NAME}=; Max-Age=0; path=/; SameSite=Lax{cookie_secure_suffix()}";
            </script>
            """,
            height=0,
        )
        return True

    token = st.session_state.pop("pending_login_cookie_token", "")
    if token:
        max_age = LOGIN_SESSION_DAYS * 24 * 60 * 60
        components.html(
            f"""
            <script>
            document.cookie = "{LOGIN_COOKIE_NAME}={token}; Max-Age={max_age}; path=/; SameSite=Lax{cookie_secure_suffix()}";
            </script>
            """,
            height=0,
        )
    return False


def apply_authenticated_account(username: str, role: str, token: str | None = None) -> None:
    normalized = normalize_username(username)
    ensure_user_account(normalized, normalize_role(role))
    st.session_state["account"] = normalized
    st.session_state["account_name"] = normalized
    st.session_state["auth_source"] = "password"
    if token:
        st.session_state["login_token"] = token


def restore_login_from_cookie() -> None:
    if st.session_state.get("account"):
        return
    token = st.session_state.get("login_token") or browser_cookie_token()
    username = login_session_username(token)
    if not username:
        return
    credential = get_account_credential(username)
    if credential is None:
        revoke_login_session(token)
        return
    apply_authenticated_account(username, credential.role, token)


def authenticate_password_account(username: str, password: str) -> tuple[bool, str]:
    normalized = normalize_username(username)
    credential = get_account_credential(normalized)
    if not credential or not verify_password(password, credential.password_hash):
        return False, "帳號或密碼錯誤。"

    token = create_login_session(normalized)
    apply_authenticated_account(normalized, credential.role, token)
    st.session_state["pending_login_cookie_token"] = token
    return True, "登入成功。"


def logout_current_user() -> None:
    revoke_login_session(st.session_state.get("login_token") or browser_cookie_token())
    for key in ("account", "account_name", "auth_source", "login_token", "pending_login_cookie_token"):
        st.session_state.pop(key, None)
    st.session_state["clear_login_cookie"] = True
    request_page_change("賽事列表")
    st.rerun()


def ensure_user_account(account_email: str, role: str = ROLE_REGISTRANT) -> None:
    normalized_role = normalize_role(role)
    db = SessionLocal()
    try:
        profile = db.query(UserProfile).filter(UserProfile.account_email == account_email).first()
        if profile is None:
            profile = UserProfile(account_email=account_email, role=normalized_role)
            db.add(profile)
        else:
            profile.role = normalize_role(profile.role)
            if normalized_role == ROLE_SUPER_ADMIN:
                profile.role = ROLE_SUPER_ADMIN
        db.commit()
    finally:
        db.close()


def get_user_profile(account_email: str | None) -> UserProfile | None:
    if not account_email:
        return None
    db = SessionLocal()
    try:
        return db.query(UserProfile).filter(UserProfile.account_email == account_email).first()
    finally:
        db.close()


def get_user_profiles() -> list[UserProfile]:
    db = SessionLocal()
    try:
        return db.query(UserProfile).order_by(UserProfile.account_email.asc()).all()
    finally:
        db.close()


def set_user_role(account_email: str, role: str) -> None:
    normalized_role = normalize_role(role)
    db = SessionLocal()
    try:
        profile = db.query(UserProfile).filter(UserProfile.account_email == account_email).first()
        if profile is None:
            profile = UserProfile(account_email=account_email, role=normalized_role)
            db.add(profile)
        else:
            profile.role = normalized_role
        db.commit()
    finally:
        db.close()


def get_event_permissions(account_email: str) -> list[EventPermission]:
    db = SessionLocal()
    try:
        return (
            db.query(EventPermission)
            .filter(
                EventPermission.account_email == account_email,
                EventPermission.permission_role == ROLE_ORGANIZER,
            )
            .order_by(EventPermission.event_id.asc())
            .all()
        )
    finally:
        db.close()


def set_event_permissions(account_email: str, event_ids: list[int]) -> None:
    db = SessionLocal()
    try:
        db.query(EventPermission).filter(EventPermission.account_email == account_email).delete()
        for event_id in event_ids:
            db.add(
                EventPermission(
                    account_email=account_email,
                    event_id=event_id,
                    permission_role=ROLE_ORGANIZER,
                )
            )
        db.commit()
    finally:
        db.close()


def organizer_event_names(account_email: str | None = None) -> list[str]:
    account = account_email or current_account()
    if not account:
        return []
    db = SessionLocal()
    try:
        permissions = (
            db.query(EventPermission, CompetitionEvent)
            .join(CompetitionEvent, EventPermission.event_id == CompetitionEvent.id)
            .filter(
                EventPermission.account_email == account,
                EventPermission.permission_role == ROLE_ORGANIZER,
            )
            .order_by(CompetitionEvent.id.desc())
            .all()
        )
        return [event.name for _, event in permissions]
    finally:
        db.close()


def admin_visible_event_names() -> list[str] | None:
    if is_admin():
        return None
    if is_organizer():
        return organizer_event_names()
    return []


def can_manage_registration_event(event_name: str) -> bool:
    if is_admin():
        return True
    return is_organizer() and event_name in organizer_event_names()


def get_team_units(account_email: str | None) -> list[TeamUnit]:
    if not account_email:
        return []
    db = SessionLocal()
    try:
        return db.query(TeamUnit).filter(TeamUnit.account_email == account_email).order_by(TeamUnit.id.asc()).all()
    finally:
        db.close()


def get_staff_members(account_email: str | None, unit_id: int | None = None) -> list[StaffMember]:
    if not account_email:
        return []
    db = SessionLocal()
    try:
        query = db.query(StaffMember).filter(StaffMember.account_email == account_email)
        if unit_id is not None:
            query = query.filter(StaffMember.unit_id == unit_id)
        return query.order_by(StaffMember.id.asc()).all()
    finally:
        db.close()


def staff_name_options(staff_members: list[StaffMember], roles: list[str]) -> list[str]:
    names = [member.name for member in staff_members if member.role in roles]
    return ["未指定"] + names


def staff_names_for_role(staff_members: list[StaffMember], role: str) -> list[str]:
    return [member.name for member in staff_members if member.role == role]


def format_staff_names(staff_members: list[StaffMember], role: str) -> str:
    names = staff_names_for_role(staff_members, role)
    return "、".join(names) if names else "尚未建立"


def save_user_profile(account_email: str, name: str, phone: str) -> None:
    db = SessionLocal()
    try:
        profile = db.query(UserProfile).filter(UserProfile.account_email == account_email).first()
        if profile is None:
            profile = UserProfile(account_email=account_email, role=ROLE_REGISTRANT)
            db.add(profile)
        elif not profile.role:
            profile.role = ROLE_REGISTRANT
        else:
            profile.role = normalize_role(profile.role)
        profile.name = name
        profile.phone = phone
        db.commit()
    finally:
        db.close()


def add_team_unit(account_email: str, unit_name: str) -> None:
    db = SessionLocal()
    try:
        db.add(TeamUnit(account_email=account_email, unit_name=unit_name))
        db.commit()
    finally:
        db.close()


def add_staff_member(account_email: str, unit_id: int, role: str, name: str, phone: str) -> None:
    db = SessionLocal()
    try:
        db.add(
            StaffMember(
                account_email=account_email,
                unit_id=unit_id,
                role=role,
                name=name,
                phone=phone,
            )
        )
        db.commit()
    finally:
        db.close()


def delete_staff_member(staff_id: int, account_email: str) -> None:
    db = SessionLocal()
    try:
        member = (
            db.query(StaffMember)
            .filter(StaffMember.id == staff_id, StaffMember.account_email == account_email)
            .first()
        )
        if member is not None:
            db.delete(member)
            db.commit()
    finally:
        db.close()


def delete_team_unit(unit_id: int, account_email: str) -> None:
    db = SessionLocal()
    try:
        db.query(StaffMember).filter(
            StaffMember.unit_id == unit_id,
            StaffMember.account_email == account_email,
        ).delete()
        unit = db.query(TeamUnit).filter(TeamUnit.id == unit_id, TeamUnit.account_email == account_email).first()
        if unit is not None:
            db.delete(unit)
        db.commit()
    finally:
        db.close()


def delete_registration(registration_id: int, account_email: str | None = None, include_all: bool = False) -> None:
    db = SessionLocal()
    try:
        query = db.query(Registration).filter(Registration.id == registration_id)
        if account_email and not include_all:
            query = query.filter(Registration.account_email == account_email)
        registration = query.first()
        if registration is not None:
            db.delete(registration)
            db.commit()
    finally:
        db.close()


def add_competition_event(name: str, registration_start: str, event_dates: str, deadline: str, venue: str, host: str, description: str, pdf_url: str) -> None:
    db = SessionLocal()
    try:
        db.add(
            CompetitionEvent(
                name=name,
                city="",
                status="",
                registration_start=registration_start,
                date=event_dates,
                deadline=deadline,
                venue=venue,
                host=host,
                description=description,
                pdf_url=pdf_url,
            )
        )
        db.commit()
    finally:
        db.close()


def update_competition_event(event_id: int, name: str, registration_start: str, event_dates: str, deadline: str, venue: str, host: str, description: str, pdf_url: str) -> None:
    db = SessionLocal()
    try:
        event = db.query(CompetitionEvent).filter(CompetitionEvent.id == event_id).first()
        if event is not None:
            event.name = name
            event.city = ""
            event.status = ""
            event.registration_start = registration_start
            event.date = event_dates
            event.deadline = deadline
            event.venue = venue
            event.host = host
            event.description = description
            event.pdf_url = pdf_url
            db.commit()
    finally:
        db.close()


def add_event_item(event_id: int, name: str, amount: int) -> None:
    db = SessionLocal()
    try:
        db.add(EventItem(event_id=event_id, name=name, amount=amount))
        db.commit()
    finally:
        db.close()


def add_event_group(item_id: int, name: str) -> None:
    db = SessionLocal()
    try:
        db.add(EventGroup(item_id=item_id, name=name))
        db.commit()
    finally:
        db.close()


def add_event_level(group_id: int, name: str) -> None:
    db = SessionLocal()
    try:
        db.add(EventLevel(group_id=group_id, name=name))
        db.commit()
    finally:
        db.close()


def delete_event_item(item_id: int) -> None:
    db = SessionLocal()
    try:
        groups = db.query(EventGroup).filter(EventGroup.item_id == item_id).all()
        for group in groups:
            db.query(EventLevel).filter(EventLevel.group_id == group.id).delete()
            db.delete(group)
        item = db.query(EventItem).filter(EventItem.id == item_id).first()
        if item is not None:
            db.delete(item)
        db.commit()
    finally:
        db.close()


def delete_event_group(group_id: int) -> None:
    db = SessionLocal()
    try:
        db.query(EventLevel).filter(EventLevel.group_id == group_id).delete()
        group = db.query(EventGroup).filter(EventGroup.id == group_id).first()
        if group is not None:
            db.delete(group)
        db.commit()
    finally:
        db.close()


def delete_event_level(level_id: int) -> None:
    db = SessionLocal()
    try:
        level = db.query(EventLevel).filter(EventLevel.id == level_id).first()
        if level is not None:
            db.delete(level)
            db.commit()
    finally:
        db.close()


def render_site_asset_preview(asset_key: str, label: str, cover: bool = False) -> None:
    asset = get_site_asset(asset_key)
    if asset is None:
        st.caption(f"尚未上傳{label}。")
        return

    image_uri = site_asset_data_uri(asset_key)
    if image_uri:
        fit = "cover" if cover else "contain"
        height = 150 if cover else 96
        st.markdown(
            f"""
            <div class="small-note">目前檔案：{escape(asset['filename'])}</div>
            <img src="{image_uri}" alt="{escape(label)}"
                 style="width:100%;height:{height}px;object-fit:{fit};border:1px solid #e3e7ed;border-radius:8px;background:#fff;padding:.4rem;">
            """,
            unsafe_allow_html=True,
        )
    if st.button(f"移除{label}", key=f"delete-{asset_key}", use_container_width=True):
        delete_site_asset(asset_key)
        st.success(f"{label}已移除。")
        st.rerun()


def render_site_asset_upload_box(asset_key: str, label: str, help_text: str, cover: bool = False) -> None:
    st.markdown(f"#### {label}")
    render_site_asset_preview(asset_key, label, cover)
    uploaded_file = st.file_uploader(
        f"上傳{label}",
        type=IMAGE_UPLOAD_TYPES,
        key=f"upload-{asset_key}",
        help=help_text,
    )
    if st.button(
        f"儲存{label}",
        key=f"save-{asset_key}",
        disabled=uploaded_file is None,
        use_container_width=True,
    ):
        save_site_asset(asset_key, uploaded_file)
        st.success(f"{label}已更新。")
        st.rerun()


def render_site_asset_admin() -> None:
    st.markdown("<div class='section-title'>網站視覺設定</div>", unsafe_allow_html=True)
    if not is_admin():
        st.error("此頁僅限最高管理員使用。")
        return

    st.caption("設定後會立即套用在左側品牌名稱、首頁標題、側邊欄 LOGO 與首頁背景。建議 LOGO 使用透明 PNG，背景圖使用橫式照片。")
    with st.form("site_identity_form"):
        name = st.text_input("網站名稱", value=site_name(), max_chars=40)
        submitted = st.form_submit_button("儲存網站名稱", use_container_width=True)
    if submitted:
        if not name.strip():
            st.error("請輸入網站名稱。")
        else:
            save_site_setting(SITE_NAME_SETTING_KEY, name)
            st.success("網站名稱已更新。")
            st.rerun()

    st.divider()
    col_logo, col_background = st.columns(2)
    with col_logo:
        render_site_asset_upload_box(
            "site_logo",
            "網站 LOGO",
            "支援 PNG、JPG、WEBP、SVG。",
        )
    with col_background:
        render_site_asset_upload_box(
            "site_background",
            "首頁背景圖片",
            "建議使用 1600px 以上的橫式圖片。",
            cover=True,
        )


def event_status_class(status: str) -> str:
    if status == "熱烈報名中":
        return "hot"
    if status == "即將開放":
        return "soon"
    return "closed"


def render_event_cards(events: list[dict]) -> None:
    for row_start in range(0, len(events), 3):
        cols = st.columns(3)
        for col, event in zip(cols, events[row_start : row_start + 3]):
            with col:
                event_date = format_public_event_date(event.get("date_raw") or event.get("date"))
                st.markdown(
                    f"""
                    <div class="event-card">
                        <span class="badge {event_status_class(event['status'])}">{escape(event['status'])}</span>
                        <h3>{escape(event['name'])}</h3>
                        <div class="event-meta">
                            <div><span>比賽日期</span><strong>{escape(event_date)}</strong></div>
                            <div><span>比賽地點</span><strong>{escape(event['venue'])}</strong></div>
                            <div><span>報名截止日期</span><strong>{escape(event['deadline'])}</strong></div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.button(
                    "查看競賽規程",
                    key=f"open-event-{event['name']}",
                    on_click=open_event_detail,
                    args=(event["name"],),
                    use_container_width=True,
                )


def render_hero(df: pd.DataFrame) -> None:
    events = [event for event in get_events() if event["status"] == "熱烈報名中"]
    current_site_name = escape(site_name())

    st.markdown(
        f"""
        <section class="hero">
            <h1>{current_site_name}</h1>
            <div class="hero-stats">
                <div class="stat"><strong>{len(events)}</strong><span>目前賽事</span></div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> str:
    with st.sidebar:
        current_site_name = escape(site_name())
        logo_uri = site_asset_data_uri("site_logo")
        if logo_uri:
            st.markdown(
                f'<img class="sidebar-logo" src="{logo_uri}" alt="網站 LOGO">',
                unsafe_allow_html=True,
            )
        else:
            logo_path = brand_logo_path()
            if logo_path:
                st.image(logo_path, width=96)
        st.markdown(
            f"""
            <div class="sidebar-brand">
                <div>
                    <strong>{current_site_name}</strong>
                    <span>{escape(DEFAULT_SITE_TAGLINE)}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        pages = visible_pages()
        if st.session_state.get("page") in PAGE_ALIASES:
            st.session_state["page"] = PAGE_ALIASES[st.session_state["page"]]
        if "page" not in st.session_state or st.session_state["page"] not in PAGES:
            st.session_state["page"] = "賽事列表"
        if "nav_page" not in st.session_state or st.session_state["nav_page"] not in pages:
            st.session_state["nav_page"] = st.session_state["page"] if st.session_state["page"] in pages else "賽事列表"
        st.button(
            "回到首頁（賽事列表）",
            key="sidebar-home-button",
            on_click=go_home,
            use_container_width=True,
        )
        st.divider()
        page = st.radio(
            "功能選單",
            pages,
            key="nav_page",
            on_change=select_nav_page,
            label_visibility="collapsed",
        )
        st.divider()
        if st.session_state.get("account"):
            profile = get_user_profile(st.session_state["account"])
            st.success(f"已登入（{role_label(profile.role if profile else current_role())}）")
            st.button(
                f"帳號：{st.session_state['account']}",
                key="sidebar-account-button",
                on_click=go_to_account_page,
                use_container_width=True,
            )
            if can_access_admin_backend():
                st.button(
                    "管理後台",
                    key="sidebar-admin-button",
                    on_click=go_to_admin_page,
                    use_container_width=True,
                )
            if is_admin():
                st.button(
                    "視覺設定",
                    key="sidebar-visual-settings-button",
                    on_click=go_to_visual_settings_page,
                    use_container_width=True,
                )
            st.button(
                "登出",
                key="sidebar-logout-button",
                on_click=logout_current_user,
                use_container_width=True,
            )
            if not get_user_profile(st.session_state["account"]):
                st.warning("請先建立聯絡人資料")
        else:
            st.button(
                "尚未登入，點此登入",
                key="sidebar-login-button",
                on_click=go_to_login_page,
                use_container_width=True,
            )
        st.divider()
        st.caption("帳號資料與報名資料會綁定目前登入帳號。")
    return st.session_state.get("page", page)


def filter_events(status_filter: str) -> list[dict]:
    events = get_events()
    if status_filter != "全部狀態":
        events = [event for event in events if event["status"] == status_filter]
    return events


def render_event_list(events: list[dict], df: pd.DataFrame) -> None:
    public_events = [event for event in events if event["status"] == "熱烈報名中"]

    render_hero(df)
    st.markdown("<div class='section-title'>目前賽事</div>", unsafe_allow_html=True)
    if public_events:
        render_event_cards(public_events)
    else:
        st.info("目前暫無開放報名的比賽。")


def render_login_box(prefix: str = "login") -> None:
    st.markdown(
        """
        <div class="login-panel">
            <h2>帳號登入</h2>
            <p>請使用系統帳號與密碼登入。一般報名人可自行建立帳號；最高管理員請使用管理員帳號登入。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    login_tab, register_tab = st.tabs(["登入", "建立帳號"])

    with login_tab:
        with st.form(f"{prefix}_password_login_form"):
            username = st.text_input("帳號", key=f"{prefix}_username", autocomplete="username")
            password = st.text_input("密碼", type="password", key=f"{prefix}_password", autocomplete="current-password")
            submitted = st.form_submit_button("登入", use_container_width=True)

        if submitted:
            ok, message = authenticate_password_account(username, password)
            if ok:
                st.success(message)
                if prefix in {"rules", "registration"} and st.session_state.get("selected_event_name"):
                    route_to_registration_or_unit_setup()
                else:
                    request_page_change("管理後台" if is_admin() else UNIT_PAGE)
                st.rerun()
            else:
                st.error(message)

    with register_tab:
        with st.form(f"{prefix}_register_form"):
            new_username = st.text_input("建立帳號", key=f"{prefix}_new_username", autocomplete="username")
            new_password = st.text_input("設定密碼", type="password", key=f"{prefix}_new_password", autocomplete="new-password")
            confirm_password = st.text_input("再次輸入密碼", type="password", key=f"{prefix}_confirm_password", autocomplete="new-password")
            register_submitted = st.form_submit_button("建立並登入", use_container_width=True)

        if register_submitted:
            if new_password != confirm_password:
                st.error("兩次輸入的密碼不一致。")
                return
            ok, message = create_password_account(new_username, new_password)
            if not ok:
                st.error(message)
                return
            authenticate_password_account(new_username, new_password)
            st.success(message)
            if prefix in {"rules", "registration"} and st.session_state.get("selected_event_name"):
                route_to_registration_or_unit_setup()
            else:
                request_page_change(UNIT_PAGE)
            st.rerun()


def render_profile_form(account_email: str, prefix: str = "profile") -> bool:
    profile = get_user_profile(account_email)
    st.caption(f"這筆聯絡人資料會綁定目前登入帳號：{account_email}")
    with st.form(f"{prefix}_form"):
        name = st.text_input("聯絡人姓名 *", value=profile.name if profile else "", key=f"{prefix}_name")
        phone = st.text_input("聯絡電話 *", value=profile.phone if profile else "", key=f"{prefix}_phone")
        submitted = st.form_submit_button("儲存聯絡人資料", use_container_width=True)

    if submitted:
        if not name.strip() or not phone.strip():
            st.error("請填寫聯絡人姓名及聯絡電話。")
        else:
            save_user_profile(account_email, name.strip(), phone.strip())
            st.success("聯絡人資料已儲存。")
            st.rerun()

    return profile is not None


def render_unit_manager(account_email: str) -> None:
    units = get_team_units(account_email)
    with st.form("team_unit_form", clear_on_submit=True):
        unit_name = st.text_input("參賽單位 / 道館名稱 *")
        submitted = st.form_submit_button("新增參賽單位", use_container_width=True)

    if submitted:
        if not unit_name.strip():
            st.error("請輸入參賽單位名稱。")
        else:
            add_team_unit(account_email, unit_name.strip())
            st.success("參賽單位已新增。")
            st.rerun()

    if not units:
        st.info("尚未建立參賽單位。")
        return

    st.dataframe(
        pd.DataFrame([{"編號": unit.id, "參賽單位": unit.unit_name} for unit in units]),
        use_container_width=True,
        hide_index=True,
    )

    st.caption("刪除單位時，該單位底下的隊職員名單也會一併移除。")
    for unit in units:
        col1, col2 = st.columns([4, 1])
        col1.write(unit.unit_name)
        if col2.button("刪除", key=f"delete-unit-{unit.id}", use_container_width=True):
            delete_team_unit(unit.id, account_email)
            st.rerun()


def render_staff_manager(account_email: str) -> None:
    units = get_team_units(account_email)
    if not units:
        st.info("請先建立參賽單位，再新增隊職員名單。")
        return

    unit_lookup = {unit.id: unit.unit_name for unit in units}
    unit_options = {unit.unit_name: unit.id for unit in units}

    selected_staff_unit = st.session_state.get("staff-member-unit")
    if selected_staff_unit not in unit_options:
        st.session_state["staff-member-unit"] = list(unit_options.keys())[0]
    if st.session_state.get("staff-member-role") not in ["領隊", "教練", "管理"]:
        st.session_state["staff-member-role"] = "領隊"
    if st.session_state.pop("clear-staff-member-name", False):
        st.session_state["staff-member-name"] = ""

    with st.form("staff_member_form"):
        unit_name = st.selectbox("所屬單位", list(unit_options.keys()), key="staff-member-unit")
        role = st.selectbox("職稱", ["領隊", "教練", "管理"], key="staff-member-role")
        name = st.text_input("姓名 *", key="staff-member-name")
        submitted = st.form_submit_button("新增隊職員", use_container_width=True)

    if submitted:
        if not name.strip():
            st.error("請輸入隊職員姓名。")
        else:
            add_staff_member(account_email, unit_options[unit_name], role, name.strip(), "")
            st.success("隊職員已新增。")
            st.session_state["clear-staff-member-name"] = True
            st.rerun()

    staff_members = get_staff_members(account_email)
    if not staff_members:
        st.info("尚未建立隊職員名單。")
        return

    roles = ["領隊", "教練", "管理"]
    for unit in units:
        unit_members = [member for member in staff_members if member.unit_id == unit.id]
        if not unit_members:
            continue

        with st.expander(unit.unit_name, expanded=True):
            for role in roles:
                role_members = [member for member in unit_members if member.role == role]
                if not role_members:
                    continue

                st.markdown(f"**{role}**")
                for member in role_members:
                    col1, col2 = st.columns([5, 1])
                    col1.markdown(f"<div style='padding-left: 1.5rem;'>{member.name}</div>", unsafe_allow_html=True)
                    if col2.button("刪除", key=f"delete-staff-{member.id}", use_container_width=True):
                        delete_staff_member(member.id, account_email)
                        st.rerun()


def render_profile_and_unit_page() -> None:
    st.markdown("<div class='section-title'>單位資料</div>", unsafe_allow_html=True)
    account = current_account()
    if not account:
        st.info("請先登入後再建立單位資料。")
        render_login_box("profile_page")
        return

    st.caption(f"目前登入帳號：{account}")
    if st.session_state.get("unit_setup_after_registration"):
        st.info("開始報名前請先建立參賽單位；完成後按下方「開始報名」即可進入賽事報名表。")

    if st.session_state.get("profile_section") not in PROFILE_SECTIONS:
        st.session_state["profile_section"] = "參賽單位"
    profile_section = st.radio(
        "資料類型",
        PROFILE_SECTIONS,
        key="profile_section",
        horizontal=True,
    )

    if profile_section == "參賽單位":
        render_unit_manager(account)
    elif profile_section == "隊職員名單":
        render_staff_manager(account)
    else:
        render_profile_form(account, "profile_page")

    st.divider()
    if st.button(
        "開始報名",
        key="profile-start-registration",
        on_click=go_to_registration_page,
        use_container_width=True,
    ):
        st.rerun()


def render_account_page() -> None:
    st.markdown("<div class='section-title'>帳號資料</div>", unsafe_allow_html=True)
    account = current_account()
    if not account:
        st.info("請先登入後再修改帳號資料。")
        render_login_box("account_page")
        return

    profile = get_user_profile(account)
    auth_label = "帳號密碼"
    st.caption(f"目前登入帳號：{account}｜登入方式：{auth_label}｜權限：{role_label(profile.role if profile else current_role())}")
    render_profile_form(account, "account_page")


@st.dialog("個人資料告知")
def render_privacy_notice_dialog(event_name: str) -> None:
    st.markdown(
        """
        報名資料將用於名單編排、資格確認、賽程通知、成績公告與現場身份核對。

        請確認選手姓名、單位、組別、聯絡電話正確；送出後若需更改，請洽主辦單位。

        主辦單位會依賽事管理需要保存報名資料，並避免將資料用於非賽事相關用途。
        """
    )
    if st.button("關閉並完成勾選", key=f"confirm-privacy-{event_name}", use_container_width=True):
        st.session_state[f"privacy-confirmed-{event_name}"] = True
        st.session_state[f"privacy-read-{event_name}"] = True
        st.rerun()


@st.dialog("安全與參賽提醒")
def render_safety_notice_dialog(event_name: str) -> None:
    st.markdown(
        """
        選手應依規定配戴護具，並由教練或監護人確認身體狀況適合參賽。

        比賽當日請攜帶身份證明文件，依大會公告時間完成報到與檢錄。

        如選手有身體不適、受傷、疾病或其他安全疑慮，請主動告知教練與大會工作人員。
        """
    )
    if st.button("關閉並完成勾選", key=f"confirm-safety-{event_name}", use_container_width=True):
        st.session_state[f"safety-confirmed-{event_name}"] = True
        st.session_state[f"safety-read-{event_name}"] = True
        st.rerun()


def render_rules(events: list[dict]) -> None:
    st.markdown("<div class='section-title'>競賽規程</div>", unsafe_allow_html=True)
    event_names = [event["name"] for event in events] or [event["name"] for event in get_events()]
    if not event_names:
        st.info("尚未建立賽事。")
        return
    current_event = st.session_state.get("selected_event_name")
    if current_event and current_event not in event_names and get_event(current_event):
        event_names = [current_event] + event_names
    if st.session_state.get("rules_event") not in event_names:
        st.session_state["rules_event"] = current_event if current_event in event_names else event_names[0]

    selected = st.selectbox("選擇要查看的賽事", event_names, key="rules_event")
    st.session_state["selected_event_name"] = selected
    event = get_event(selected)
    if event is None:
        st.error("找不到此賽事。")
        return

    left, right = st.columns([1.5, 1])
    with left:
        st.markdown(
            f"""
            <div class="info-panel">
                <h3>{event['name']}</h3>
                <p><strong>主辦單位：</strong>{event['host']}</p>
                <p><strong>比賽日期：</strong>{event['date']}</p>
                <p><strong>比賽地點：</strong>{event['venue']}</p>
                <p><strong>報名開始：</strong>{event['registration_start']}</p>
                <p><strong>報名截止：</strong>{event['deadline']}</p>
                <p><strong>報名費：</strong>NT${event['fee']:,} / 人</p>
                <p>{event['description']}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        st.markdown("#### 報名項目階層")
        event_items = get_event_items(selected)
        if not event_items:
            st.info("此賽事尚未設定報名項目。")
        for event_item in event_items:
            with st.expander(f"{event_item.name} / NT${event_item.amount or 0:,}", expanded=False):
                groups = get_event_groups(event_item.id)
                if not groups:
                    st.caption("尚未設定組別。")
                for group in groups:
                    levels = get_event_levels(group.id)
                    level_text = "、".join(level.name for level in levels) if levels else "尚未設定級別"
                    st.write(f"{group.name}：{level_text}")

    pdf_embed_url = google_drive_pdf_embed_url(event.get("pdf_url"))
    if pdf_embed_url:
        st.markdown("<div class='section-title'>競賽規程 PDF</div>", unsafe_allow_html=True)
        st.components.v1.iframe(pdf_embed_url, height=720, scrolling=True)

    st.markdown("<div class='section-title'>報名前提醒</div>", unsafe_allow_html=True)
    st.caption("勾選個人資料告知或安全提醒時，系統會開啟彈跳提醒；按下關閉後才會完成勾選。")

    privacy_key = f"privacy-read-{selected}"
    safety_key = f"safety-read-{selected}"
    privacy_confirmed_key = f"privacy-confirmed-{selected}"
    safety_confirmed_key = f"safety-confirmed-{selected}"

    if st.session_state.get(privacy_confirmed_key):
        st.session_state[privacy_key] = True
    if st.session_state.get(safety_confirmed_key):
        st.session_state[safety_key] = True

    privacy_read = st.checkbox(
        "我已閱讀並同意個人資料蒐集、處理與利用告知",
        key=privacy_key,
        disabled=st.session_state.get(privacy_confirmed_key, False),
    )
    safety_read = st.checkbox(
        "我已閱讀安全提醒，並會確認選手具備參賽狀態",
        key=safety_key,
        disabled=st.session_state.get(safety_confirmed_key, False),
    )

    if privacy_read and not st.session_state.get(privacy_confirmed_key):
        render_privacy_notice_dialog(selected)
    elif safety_read and not st.session_state.get(safety_confirmed_key):
        render_safety_notice_dialog(selected)

    notices_ready = (
        st.session_state.get(privacy_confirmed_key, False)
        and st.session_state.get(safety_confirmed_key, False)
    )
    if notices_ready:
        st.session_state[notice_key(selected)] = True

    if event["status"] == "報名已截止":
        st.error("此賽事已截止報名，僅開放查看規程。")
        return

    if not st.session_state.get("account"):
        st.info("閱讀提醒後，請登入帳號再進行報名。")
        render_login_box("rules")
        return

    st.button(
        "前往線上報名",
        key=f"go-register-{selected}",
        on_click=start_registration,
        args=(selected,),
        use_container_width=True,
        disabled=not notices_ready,
    )
    if not notices_ready:
        st.caption("請先完成個資告知與安全提醒。")


def reset_registration_form_state(event_name: str, default_unit_name: str) -> None:
    st.session_state[f"athlete-unit::{event_name}"] = default_unit_name
    st.session_state[f"athlete-unit-last::{event_name}"] = default_unit_name
    st.session_state[f"registration-items::{event_name}"] = []

    for key in [
        f"athlete-name::{event_name}",
        f"athlete-gender::{event_name}",
        f"athlete-birth::{event_name}-date",
        f"item-category::{event_name}",
        f"item-group::{event_name}",
        f"item-rank::{event_name}",
        f"last-item-id::{event_name}",
        f"last-group-id::{event_name}",
        f"item-note::{event_name}",
        f"registration-agreement::{event_name}",
    ]:
        st.session_state.pop(key, None)


def registered_athletes_dataframe(account_email: str, event_name: str) -> pd.DataFrame:
    db = SessionLocal()
    try:
        registrations = (
            db.query(Registration)
            .filter(
                Registration.account_email == account_email,
                Registration.event_name == event_name,
            )
            .order_by(Registration.id.desc())
            .all()
        )
        return pd.DataFrame(
            [
                {
                    "選手姓名": item.athlete_name,
                    "單位": item.team_name,
                    "性別": item.gender,
                    "出生年月日": getattr(item, "birth_date", "") or "",
                    "項目": item.category,
                    "組別": getattr(item, "group_name", "") or item.level,
                    "級別": getattr(item, "rank_level", "") or "",
                    "金額": getattr(item, "item_amount", 0) or 0,
                    "備註": getattr(item, "note", "") or "",
                }
                for item in registrations
            ]
        )
    finally:
        db.close()


def render_registered_athletes(account_email: str, event_name: str) -> None:
    st.markdown("<div class='section-title'>已報名選手</div>", unsafe_allow_html=True)
    registered_df = registered_athletes_dataframe(account_email, event_name)
    if registered_df.empty:
        st.info("此賽事目前尚未送出報名選手。")
        return
    st.dataframe(registered_df, use_container_width=True, hide_index=True)


def render_registration_form() -> None:
    st.markdown("<div class='section-title'>賽事報名表</div>", unsafe_allow_html=True)

    if not st.session_state.get("account"):
        st.info("請先登入後再進行報名。")
        render_login_box("registration")
        return

    selected_event = get_event(st.session_state.get("selected_event_name"))
    if not selected_event:
        active_events = [event for event in get_events() if event["status"] != "報名已截止"]
        st.info("請先從賽事列表選擇要報名的比賽。")
        render_event_cards(active_events)
        return

    event_name = selected_event["name"]
    reset_key = f"registration-reset::{event_name}"
    success_key = f"registration-success::{event_name}"
    if selected_event["status"] == "報名已截止":
        st.error("此賽事已截止報名，請選擇其他前台賽事。")
        return

    if not notices_confirmed(event_name):
        st.warning("請先閱讀個資告知與安全提醒，確認後才可進入報名表。")
        st.button(
            "前往競賽規程",
            key=f"back-to-rules-{event_name}",
            on_click=open_event_detail,
            args=(event_name,),
            use_container_width=True,
        )
        return
    st.session_state[notice_key(event_name)] = True

    account = current_account()
    profile = get_user_profile(account)
    if not profile:
        st.warning("登入後須先建立聯絡人資料，填寫聯絡人姓名與聯絡電話後才能報名。")
        render_profile_form(account, "registration_profile")
        return

    units = get_team_units(account)
    if not units:
        st.session_state["profile_section"] = "參賽單位"
        st.session_state["unit_setup_after_registration"] = True
        request_page_change(UNIT_PAGE)
        st.warning("尚未建立參賽單位，已為你前往單位建立區。")
        st.rerun()

    unit_options = {unit.unit_name: unit for unit in units}
    event_date_display = format_event_date_range(selected_event.get("date_raw") or selected_event.get("date"))
    unit_names = list(unit_options.keys())
    if st.session_state.get("registration_unit_name") not in unit_names:
        st.session_state["registration_unit_name"] = unit_names[0]
    if st.session_state.pop(reset_key, False):
        reset_registration_form_state(event_name, st.session_state["registration_unit_name"])

    st.markdown(
        f"""
        <div class="info-panel">
            <h3>{event_name}</h3>
            <p><strong>比賽日期：</strong>{event_date_display}　<strong>地點：</strong>{selected_event['venue']}</p>
            <p><strong>報名期間：</strong>{selected_event['registration_start']} 至 {selected_event['deadline']}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    success_message = st.session_state.pop(success_key, None)
    if success_message:
        st.success(success_message)

    if st.button(
        "編輯單位資料",
        key="registration-edit-profile",
        on_click=go_to_profile_page,
        use_container_width=True,
    ):
        st.rerun()

    st.subheader("1. 單位")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        selected_unit_name = st.selectbox("參賽單位", unit_names, key="registration_unit_name")
        selected_unit = unit_options[selected_unit_name]
        unit_staff = get_staff_members(account, selected_unit.id)

    leader_names = "、".join(staff_names_for_role(unit_staff, "領隊"))
    coach_names = "、".join(staff_names_for_role(unit_staff, "教練"))
    manager_names = "、".join(staff_names_for_role(unit_staff, "管理"))
    with col2:
        st.text_area("領隊", value=format_staff_names(unit_staff, "領隊"), disabled=True, height=82)
    with col3:
        st.text_area("教練", value=format_staff_names(unit_staff, "教練"), disabled=True, height=82)
    with col4:
        st.text_area("管理", value=format_staff_names(unit_staff, "管理"), disabled=True, height=82)

    athlete_unit_key = f"athlete-unit::{event_name}"
    last_unit_key = f"athlete-unit-last::{event_name}"
    if st.session_state.get(last_unit_key) != selected_unit_name:
        st.session_state[athlete_unit_key] = selected_unit_name
        st.session_state[last_unit_key] = selected_unit_name

    st.subheader("2. 選手參賽資料")
    col5, col6, col7 = st.columns(3)
    with col5:
        athlete_unit_name = st.text_input("單位 *", key=athlete_unit_key)
    with col6:
        athlete_name = st.text_input("姓名 *", key=f"athlete-name::{event_name}")
    with col7:
        gender = st.selectbox("性別", ["男", "女"], key=f"athlete-gender::{event_name}")

    birth_date = render_date_picker("出生年月日", date.today(), f"athlete-birth::{event_name}")

    st.subheader("3. 參賽項目")
    items_key = f"registration-items::{event_name}"
    if items_key not in st.session_state:
        st.session_state[items_key] = []

    event_items = get_event_items(event_name)
    if not event_items:
        st.warning("此賽事尚未設定項目，請洽管理員。")
        return

    item_options = {f"{item.name}（NT${item.amount or 0:,}）": item for item in event_items}
    item_key = f"item-category::{event_name}"
    group_key = f"item-group::{event_name}"
    level_key = f"item-rank::{event_name}"
    last_item_key = f"last-item-id::{event_name}"
    last_group_key = f"last-group-id::{event_name}"

    item_label = st.selectbox("1. 項目", list(item_options.keys()), key=item_key)
    selected_item = item_options[item_label]

    event_groups = get_event_groups(selected_item.id)
    if not event_groups:
        st.warning("此項目尚未設定組別，請先由後台新增組別。")
        return

    group_options = {group.name: group for group in event_groups}
    if st.session_state.get(last_item_key) != selected_item.id:
        st.session_state[group_key] = list(group_options.keys())[0]
        st.session_state[level_key] = "請選擇"
        st.session_state[last_item_key] = selected_item.id
    if st.session_state.get(group_key) not in group_options:
        st.session_state[group_key] = list(group_options.keys())[0]

    group_name = st.selectbox("2. 組別（隸屬於上方項目）", list(group_options.keys()), key=group_key)
    selected_group = group_options[group_name]

    event_levels = get_event_levels(selected_group.id)
    level_options = [level.name for level in event_levels]
    if not level_options:
        st.warning("此組別尚未設定級別，請先由後台新增級別。")
        return

    if st.session_state.get(last_group_key) != selected_group.id:
        st.session_state[level_key] = "請選擇"
        st.session_state[last_group_key] = selected_group.id
    if st.session_state.get(level_key) not in ["請選擇"] + level_options:
        st.session_state[level_key] = "請選擇"

    rank_level = st.selectbox("3. 級別（隸屬於上方組別）", ["請選擇"] + level_options, key=level_key)
    st.caption(f"目前階層：{selected_item.name} > {group_name} > {rank_level if rank_level != '請選擇' else '請選擇級別'}")
    item_note = st.text_input("項目備註", placeholder="例如：特殊需求、量級補充，可留空", key=f"item-note::{event_name}")

    if st.button("新增參賽項目", key=f"add-registration-item::{event_name}", use_container_width=True):
        if rank_level == "請選擇":
            st.error("請先選擇級別。")
        else:
            st.session_state[items_key].append(
                {
                    "category": selected_item.name,
                    "group_name": group_name,
                    "rank_level": rank_level,
                    "amount": selected_item.amount or 0,
                    "note": item_note.strip(),
                }
            )
            st.rerun()

    selected_items = st.session_state[items_key]
    if selected_items:
        for index, item in enumerate(selected_items):
            col_a, col_b = st.columns([5, 1])
            col_a.markdown(
                f"**{index + 1}. {item['category']}**　{item['group_name']} / {item['rank_level']} / NT${item.get('amount', 0):,}"
                + (f"　備註：{item['note']}" if item["note"] else "")
            )
            if col_b.button("刪除", key=f"delete-registration-item::{event_name}::{index}", use_container_width=True):
                selected_items.pop(index)
                st.rerun()
    else:
        st.info("尚未新增參賽項目。請先新增至少一個項目。")

    agreement = st.checkbox(
        "我已確認資料正確，並同意主辦單位依賽事需要處理報名資料",
        key=f"registration-agreement::{event_name}",
    )
    if st.button("儲存並提交本筆資料", key=f"submit-registration::{event_name}", use_container_width=True):
        missing = []
        if not athlete_name.strip():
            missing.append("選手姓名")
        if not athlete_unit_name.strip():
            missing.append("單位")
        if not selected_items:
            missing.append("至少一個參賽項目")
        if not agreement:
            missing.append("同意條款")

        if missing:
            st.error("請補齊：" + "、".join(missing))
            return

        db = SessionLocal()
        try:
            for item in selected_items:
                full_level = f"{item['group_name']} / {item['rank_level']}"
                db.add(
                    Registration(
                        account_email=account,
                        event_name=event_name,
                        team_name=athlete_unit_name.strip(),
                        leader_name=leader_names,
                        coach_name=coach_names,
                        manager_name=manager_names,
                        athlete_name=athlete_name.strip(),
                        gender=gender,
                        birth_date=birth_date.isoformat() if birth_date else "",
                        category=item["category"],
                        group_name=item["group_name"],
                        rank_level=item["rank_level"],
                        level=full_level,
                        item_amount=item.get("amount", 0),
                        note=item["note"],
                        phone=profile.phone,
                    )
                )
            db.commit()
            st.session_state[reset_key] = True
            st.session_state[success_key] = f"{athlete_name.strip()} 報名成功，表單已清空。"
        finally:
            db.close()
        st.rerun()

    render_registered_athletes(account, event_name)


def render_my_registrations(df: pd.DataFrame) -> None:
    st.markdown("<div class='section-title'>我的報名管理中心</div>", unsafe_allow_html=True)
    if not current_account():
        st.info("請先登入後查看自己的報名名單。")
        render_login_box("my_registrations")
        return
    search = st.text_input("搜尋單位、教練、選手或電話")
    filtered = df
    if search and not df.empty:
        mask = df.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
        filtered = df[mask]

    estimated_fee = int(filtered["金額"].sum()) if not filtered.empty and "金額" in filtered else 0
    col_count, col_fee = st.columns(2)
    col_count.metric("目前顯示筆數", len(filtered))
    col_fee.metric("目前系統預估報名費合計", f"NT${estimated_fee:,}")
    display_df = filtered if is_admin() else filtered.drop(columns=["帳號"], errors="ignore")
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    if not filtered.empty:
        st.subheader("刪除報名項目")
        for _, row in filtered.iterrows():
            registration_id = int(row["編號"])
            summary = (
                f"{registration_id}. {row['選手姓名']} / {row['報名單位']} / "
                f"{row['項目']} / {row['組別']} / {row['級別']}"
            )
            col1, col2 = st.columns([5, 1])
            col1.write(summary)
            if col2.button("刪除", key=f"delete-registration-{registration_id}", use_container_width=True):
                delete_registration(registration_id, current_account(), is_admin())
                st.rerun()
    if not filtered.empty:
        st.markdown("### 💰 填寫匯款回報中心")
        unique_events = filtered["賽事"].unique()
        selected_pay_event = st.selectbox("選擇要回報的賽事", unique_events, key="pay_event_sel")
        
        event_df = filtered[filtered["賽事"] == selected_pay_event]
        total_pay_need = event_df["金額"].sum()
        st.info(f"您在此賽事【{selected_pay_event}】的應繳總金額為：NT${total_pay_need:,}")
        
        with st.form("payment_report_form"):
            five_digits = st.text_input("匯款帳號後五碼 *", max_chars=5, placeholder="12345")
            pay_remark = st.text_input("備註說明（選填）", placeholder="預計X月X日轉帳 / 匯款人姓名")
            pay_submit = st.form_submit_button("送出匯款回報", use_container_width=True)
            
            if pay_submit:
                if len(five_digits.strip()) != 5:
                    st.error("請輸入正確的 5 位數帳號後五碼。")
                else:
                    update_payment_info(current_account(), selected_pay_event, five_digits.strip(), pay_remark.strip())
                    st.success("回報成功！狀態已更新為「待核對」，請靜候主辦單位查收。")
                    st.rerun()
    st.download_button(
        "下載目前名單 Excel",
        data=dataframe_to_excel(display_df),
        file_name="報名名單匯出.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        disabled=filtered.empty,
    )


HIERARCHY_HUES = [354, 212, 168, 32, 276, 190, 112, 15, 238, 320]


def hierarchy_colors(index: int) -> dict[str, str]:
    hue = HIERARCHY_HUES[index % len(HIERARCHY_HUES)]
    return {
        "item_bg": f"hsl({hue}, 68%, 42%)",
        "item_fg": "#ffffff",
        "item_border": f"hsl({hue}, 68%, 34%)",
        "item_accent": f"hsl({hue}, 82%, 58%)",
        "group_bg": f"hsl({hue}, 72%, 91%)",
        "group_fg": f"hsl({hue}, 48%, 24%)",
        "group_border": f"hsl({hue}, 58%, 70%)",
        "group_accent": f"hsl({hue}, 68%, 48%)",
        "level_bg": f"hsl({hue}, 76%, 96%)",
        "level_fg": f"hsl({hue}, 42%, 24%)",
        "level_border": f"hsl({hue}, 52%, 80%)",
        "level_accent": f"hsl({hue}, 62%, 56%)",
    }


def hierarchy_node_html(kind: str, name: str, level: str, colors: dict[str, str], icon: str = "", meta: str = "") -> str:
    safe_icon = escape(icon)
    safe_kind = escape(kind)
    safe_name = escape(name)
    safe_meta = escape(meta)
    meta_html = f"<span class='hierarchy-meta'>{safe_meta}</span>" if meta else ""
    return f"""
    <div
        class="hierarchy-node hierarchy-node-{level}"
        style="--node-bg: {colors[f'{level}_bg']}; --node-fg: {colors[f'{level}_fg']}; --node-border: {colors[f'{level}_border']}; --node-accent: {colors[f'{level}_accent']};"
    >
        <span class="hierarchy-caret">{safe_icon}</span>
        <span class="hierarchy-kind">{safe_kind}</span>
        <strong>{safe_name}</strong>
        {meta_html}
    </div>
    """


def hierarchy_empty_html(message: str, level: str, colors: dict[str, str]) -> str:
    return f"""
    <div
        class="hierarchy-empty"
        style="border-color: {colors[f'{level}_border']}; background: {colors[f'{level}_bg']}; color: {colors[f'{level}_fg']};"
    >
        {escape(message)}
    </div>
    """


def render_event_hierarchy_tree(event_name: str) -> None:
    items = get_event_items(event_name)
    if not items:
        st.info("此賽事尚未建立項目。")
        return

    st.markdown("### 項目 > 組別 > 級別")
    st.caption("點開項目可設定該項目內的所有組別；點開單一組別可設定該組別內的所有級別。")

    open_item_key = f"admin-open-item::{event_name}"
    open_group_key = f"admin-open-group::{event_name}"

    for item_index, item in enumerate(items):
        colors = hierarchy_colors(item_index)
        item_is_open = st.session_state.get(open_item_key) == item.id
        item_icon = "▼" if item_is_open else "▶"
        item_label_col, item_toggle_col, delete_col = st.columns([4.1, 0.9, 1])

        item_label_col.markdown(
            hierarchy_node_html("項目", item.name, "item", colors, item_icon, f"NT${item.amount or 0:,}"),
            unsafe_allow_html=True,
        )
        if item_toggle_col.button(
            "收合" if item_is_open else "展開",
            key=f"toggle-event-item-{item.id}",
            use_container_width=True,
        ):
            if item_is_open:
                st.session_state.pop(open_item_key, None)
                st.session_state.pop(open_group_key, None)
            else:
                st.session_state[open_item_key] = item.id
                st.session_state.pop(open_group_key, None)

        if delete_col.button(
            "刪除項目",
            key=f"delete-event-item-{item.id}",
            use_container_width=True,
        ):
            delete_event_item(item.id)
            st.session_state.pop(open_item_key, None)
            st.session_state.pop(open_group_key, None)
            st.rerun()

        if st.session_state.get(open_item_key) != item.id:
            continue

        _, group_form_col = st.columns([0.45, 5.55])
        with group_form_col:
            with st.form(f"add_group_form::{item.id}", clear_on_submit=True):
                group_name = st.text_input(
                    "新增組別",
                    placeholder="例如：國小低年級、10-11歲男",
                    key=f"new-group-name::{item.id}",
                )
                group_submitted = st.form_submit_button("新增到此項目", use_container_width=True)
        if group_submitted:
            if not group_name.strip():
                st.error("請輸入組別名稱。")
            else:
                add_event_group(item.id, group_name.strip())
                st.success("組別已新增。")
                st.rerun()

        groups = get_event_groups(item.id)
        if not groups:
            _, empty_group_col = st.columns([0.45, 5.55])
            empty_group_col.markdown(
                hierarchy_empty_html("此項目尚未建立組別。", "group", colors),
                unsafe_allow_html=True,
            )
            st.divider()
            continue

        for group in groups:
            group_is_open = st.session_state.get(open_group_key) == group.id
            group_icon = "▼" if group_is_open else "▶"
            _, group_label_col, group_toggle_col, group_delete_col = st.columns([0.45, 3.65, 0.9, 1])

            group_label_col.markdown(
                hierarchy_node_html("組別", group.name, "group", colors, group_icon),
                unsafe_allow_html=True,
            )
            if group_toggle_col.button(
                "收合" if group_is_open else "展開",
                key=f"toggle-event-group-{group.id}",
                use_container_width=True,
            ):
                if group_is_open:
                    st.session_state.pop(open_group_key, None)
                else:
                    st.session_state[open_group_key] = group.id

            if group_delete_col.button(
                "刪除組別",
                key=f"delete-event-group-{group.id}",
                use_container_width=True,
            ):
                delete_event_group(group.id)
                st.session_state.pop(open_group_key, None)
                st.rerun()

            if st.session_state.get(open_group_key) != group.id:
                continue

            _, level_form_col = st.columns([0.9, 5.1])
            with level_form_col:
                with st.form(f"add_level_form::{group.id}", clear_on_submit=True):
                    level_name = st.text_input(
                        "新增級別",
                        placeholder="例如：白帶、黑帶一段、-45kg",
                        key=f"new-level-name::{group.id}",
                    )
                    level_submitted = st.form_submit_button("新增到此組別", use_container_width=True)
            if level_submitted:
                if not level_name.strip():
                    st.error("請輸入級別名稱。")
                else:
                    add_event_level(group.id, level_name.strip())
                    st.success("級別已新增。")
                    st.rerun()

            levels = get_event_levels(group.id)
            if not levels:
                _, empty_level_col = st.columns([0.9, 5.1])
                empty_level_col.markdown(
                    hierarchy_empty_html("此組別尚未建立級別。", "level", colors),
                    unsafe_allow_html=True,
                )
                continue

            for level in levels:
                _, level_col, level_delete_col = st.columns([0.9, 4.1, 1])
                level_col.markdown(
                    hierarchy_node_html("級別", level.name, "level", colors),
                    unsafe_allow_html=True,
                )
                if level_delete_col.button(
                    "刪除級別",
                    key=f"delete-event-level-{level.id}",
                    use_container_width=True,
                ):
                    delete_event_level(level.id)
                    st.rerun()

        st.divider()


def render_event_admin() -> None:
    st.subheader("新增賽事")
    with st.form("add_event_form", clear_on_submit=True):
        name = st.text_input("賽事名稱 *")
        col1, col2 = st.columns(2)
        with col1:
            registration_start_value = render_datetime_picker(
                "報名開始",
                datetime.combine(date.today(), time(0, 0, 0)),
                "add-registration-start",
            )
        with col2:
            deadline_value = render_datetime_picker(
                "報名截止",
                datetime.combine(date.today(), time(23, 59, 59)),
                "add-registration-deadline",
            )
        event_dates = render_date_range_picker("比賽日期", (date.today(), date.today()), "add-event-date")
        venue = st.text_input("比賽地點")
        host = st.text_input("主辦單位")
        pdf_url = st.text_input("競賽規程（Google Drive 分享連結或檔案 ID）")
        description = st.text_area("項目說明")
        submitted = st.form_submit_button("新增賽事", use_container_width=True)

    if submitted:
        if not name.strip():
            st.error("請輸入賽事名稱。")
        else:
            add_competition_event(
                name.strip(),
                registration_start_value,
                "\n".join(event_dates),
                deadline_value,
                venue.strip(),
                host.strip(),
                description.strip(),
                pdf_url.strip(),
            )
            st.success("賽事已新增。")
            st.rerun()

    events = get_events()
    if not events:
        st.info("尚未建立賽事。")
        return

    st.subheader("編輯賽事與項目")
    event_options = {event["name"]: event for event in events}
    selected_event_name = st.selectbox("選擇賽事", list(event_options.keys()), key="admin-event-selector")
    selected_event = event_options[selected_event_name]

    with st.form("update_event_form"):
        edit_name = st.text_input("賽事名稱", value=selected_event["name"])
        start_dt = parse_datetimeish(selected_event.get("registration_start")) or datetime.now()
        deadline_dt = parse_datetimeish(selected_event["deadline"]) or datetime.now()
        col1, col2 = st.columns(2)
        with col1:
            edit_registration_start_value = render_datetime_picker(
                "報名開始",
                start_dt,
                "edit-registration-start",
            )
        with col2:
            edit_deadline_value = render_datetime_picker(
                "報名截止",
                deadline_dt,
                "edit-registration-deadline",
            )
        edit_dates = render_date_range_picker(
            "比賽日期",
            date_range_default(selected_event.get("date_raw") or selected_event.get("date")),
            "edit-event-date",
        )
        edit_venue = st.text_input("比賽地點", value=selected_event["venue"])
        edit_host = st.text_input("主辦單位", value=selected_event["host"])
        edit_pdf_url = st.text_input("競賽規程（Google Drive 分享連結或檔案 ID）", value=selected_event.get("pdf_url", ""))
        edit_description = st.text_area("項目說明", value=selected_event["description"])
        st.text_input("狀態（自動判斷）", value=selected_event["status"], disabled=True)
        update_submitted = st.form_submit_button("更新賽事資料", use_container_width=True)

    if update_submitted:
        update_competition_event(
            selected_event["id"],
            edit_name.strip(),
            edit_registration_start_value,
            "\n".join(edit_dates),
            edit_deadline_value,
            edit_venue.strip(),
            edit_host.strip(),
            edit_description.strip(),
            edit_pdf_url.strip(),
        )
        st.success("賽事資料已更新。")
        st.rerun()

    st.markdown("### 1. 項目（最上層）與金額")
    with st.form("add_item_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            item_name = st.text_input("項目名稱 *", placeholder="例如：對打、個人品勢、速度踢")
        with col2:
            item_amount = st.number_input("金額", min_value=0, step=100, value=0)
        item_submitted = st.form_submit_button("新增項目", use_container_width=True)

    if item_submitted:
        if not item_name.strip():
            st.error("請輸入項目名稱。")
        else:
            add_event_item(selected_event["id"], item_name.strip(), int(item_amount))
            st.success("項目已新增。")
            st.rerun()

    items = get_event_items(selected_event["name"])
    if not items:
        st.info("此賽事尚未建立項目。")
        return

    render_event_hierarchy_tree(selected_event["name"])


def update_registration_record(registration_id: int, fields: dict[str, str | int]) -> bool:
    db = SessionLocal()
    try:
        registration = db.query(Registration).filter(Registration.id == registration_id).first()
        if registration is None or not can_manage_registration_event(registration.event_name):
            return False
        registration.team_name = str(fields["team_name"])
        registration.athlete_name = str(fields["athlete_name"])
        registration.gender = str(fields["gender"])
        registration.birth_date = str(fields["birth_date"])
        registration.category = str(fields["category"])
        registration.group_name = str(fields["group_name"])
        registration.rank_level = str(fields["rank_level"])
        registration.level = f"{fields['group_name']} / {fields['rank_level']}"
        registration.item_amount = int(fields["item_amount"])
        registration.leader_name = str(fields["leader_name"])
        registration.coach_name = str(fields["coach_name"])
        registration.manager_name = str(fields["manager_name"])
        registration.phone = str(fields["phone"])
        registration.note = str(fields["note"])
        registration.payment_status = str(fields["payment_status"])
        registration.pay_five_digits = str(fields["pay_five_digits"])
        db.commit()
        return True
    finally:
        db.close()


def render_admin_registration_editor(view: pd.DataFrame) -> None:
    if view.empty:
        return

    st.markdown("### 修改選手與單位資料")
    row_options = {
        f"{int(row['編號'])}. {row['賽事']} / {row['選手姓名']} / {row['報名單位']}": int(row["編號"])
        for _, row in view.iterrows()
    }
    selected_label = st.selectbox("選擇要修改的報名資料", list(row_options.keys()), key="admin-registration-edit-select")
    selected_id = row_options[selected_label]
    selected_row = view[view["編號"] == selected_id].iloc[0]

    with st.form(f"admin-registration-edit-form-{selected_id}"):
        col1, col2, col3 = st.columns(3)
        with col1:
            team_name = st.text_input("報名單位", value=str(selected_row["報名單位"]))
            athlete_name = st.text_input("選手姓名", value=str(selected_row["選手姓名"]))
            gender_options = ["男", "女", "其他"]
            current_gender = str(selected_row["性別"])
            gender = st.selectbox(
                "性別",
                gender_options,
                index=gender_options.index(current_gender) if current_gender in gender_options else 0,
            )
        with col2:
            birth_date = st.text_input("出生年月日", value=str(selected_row["出生年月日"]))
            category = st.text_input("項目", value=str(selected_row["項目"]))
            group_name = st.text_input("組別", value=str(selected_row["組別"]))
        with col3:
            rank_level = st.text_input("級別", value=str(selected_row["級別"]))
            item_amount = st.number_input("金額", min_value=0, step=100, value=int(selected_row["金額"] or 0))
            phone = st.text_input("電話", value=str(selected_row["電話"]))

        col4, col5, col6 = st.columns(3)
        with col4:
            leader_name = st.text_input("領隊", value=str(selected_row["領隊"]))
        with col5:
            coach_name = st.text_input("教練", value=str(selected_row["教練"]))
        with col6:
            manager_name = st.text_input("管理", value=str(selected_row["管理"]))

        status_options = ["未繳費", "待核對", "已確認"]
        current_status = str(selected_row["繳費狀態"])
        payment_status = st.selectbox(
            "繳費狀態",
            status_options,
            index=status_options.index(current_status) if current_status in status_options else 0,
        )
        pay_five_digits = st.text_input("匯款後五碼", value=str(selected_row["匯款後五碼"]), max_chars=5)
        note = st.text_area("備註", value=str(selected_row["備註"]))
        submitted = st.form_submit_button("儲存修改", use_container_width=True)

    if submitted:
        if not athlete_name.strip() or not team_name.strip():
            st.error("報名單位與選手姓名不可空白。")
            return
        updated = update_registration_record(
            selected_id,
            {
                "team_name": team_name.strip(),
                "athlete_name": athlete_name.strip(),
                "gender": gender,
                "birth_date": birth_date.strip(),
                "category": category.strip(),
                "group_name": group_name.strip(),
                "rank_level": rank_level.strip(),
                "item_amount": int(item_amount),
                "leader_name": leader_name.strip(),
                "coach_name": coach_name.strip(),
                "manager_name": manager_name.strip(),
                "phone": phone.strip(),
                "note": note.strip(),
                "payment_status": payment_status,
                "pay_five_digits": pay_five_digits.strip(),
            },
        )
        if updated:
            st.success("報名資料已更新。")
            st.rerun()
        st.error("你沒有權限修改此筆資料。")

    if st.button("刪除此筆報名", key=f"admin-delete-registration-{selected_id}", use_container_width=True):
        if can_manage_registration_event(str(selected_row["賽事"])):
            delete_registration(selected_id, include_all=True)
            st.success("報名資料已刪除。")
            st.rerun()
        st.error("你沒有權限刪除此筆資料。")


def render_permission_admin() -> None:
    st.subheader("權限管理")
    events = get_events()
    event_options = {event["name"]: event["id"] for event in events}
    profiles = get_user_profiles()
    profile_emails = [profile.account_email for profile in profiles]

    selected_existing = st.selectbox(
        "選擇既有帳號",
        ["新增帳號"] + profile_emails,
        key="permission-existing-account",
    )
    if selected_existing == "新增帳號":
        target_email = st.text_input("帳號", key="permission-new-email").strip().lower()
    else:
        st.text_input("帳號", value=selected_existing, disabled=True, key="permission-existing-email")
        target_email = selected_existing.strip().lower()
    target_profile = get_user_profile(target_email) if target_email else None
    current_role_label = role_label(target_profile.role if target_profile else ROLE_REGISTRANT)
    role_names = list(ROLE_OPTIONS.keys())
    selected_role_name = st.selectbox(
        "權限角色",
        role_names,
        index=role_names.index(current_role_label) if current_role_label in role_names else role_names.index("報名人"),
        key="permission-role",
    )
    existing_event_names = organizer_event_names(target_email) if target_email else []
    selected_event_names = st.multiselect(
        "主辦單位可管理的賽事",
        list(event_options.keys()),
        default=[name for name in existing_event_names if name in event_options],
        disabled=ROLE_OPTIONS[selected_role_name] != ROLE_ORGANIZER,
        key="permission-events",
    )
    if st.button("儲存權限", key="save-permission", use_container_width=True):
        if not target_email:
            st.error("請輸入帳號。")
            return
        selected_role = ROLE_OPTIONS[selected_role_name]
        if target_email == current_account() and selected_role != ROLE_SUPER_ADMIN:
            st.error("不能移除自己目前的最高管理員權限。")
            return
        set_user_role(target_email, selected_role)
        selected_event_ids = [event_options[name] for name in selected_event_names] if selected_role == ROLE_ORGANIZER else []
        set_event_permissions(target_email, selected_event_ids)
        st.success("權限已更新。")
        st.rerun()

    st.markdown("### 目前帳號權限")
    rows = [
        {
            "帳號": profile.account_email,
            "角色": role_label(profile.role),
            "授權賽事": "、".join(organizer_event_names(profile.account_email)) or "-",
        }
        for profile in profiles
    ]
    st.dataframe(pd.DataFrame(rows, columns=["帳號", "角色", "授權賽事"]), use_container_width=True, hide_index=True)


def render_admin(df: pd.DataFrame) -> None:
    st.markdown("<div class='section-title'>管理後台</div>", unsafe_allow_html=True)
    if not can_access_admin_backend():
        st.error("此頁僅限最高管理員與主辦單位使用。")
        return

    all_events = get_events()
    visible_event_names = admin_visible_event_names()
    visible_events = all_events if visible_event_names is None else [
        event for event in all_events if event["name"] in visible_event_names
    ]
    if not is_admin() and not visible_events:
        st.warning("目前尚未被授權管理任何賽事，請聯繫最高管理員設定權限。")
        return

    all_label = "全部賽事" if is_admin() else "全部授權賽事"
    event_filter = st.selectbox("請選擇要查看的賽事", [all_label] + [event["name"] for event in visible_events])
    view = df if event_filter == all_label or df.empty else df[df["賽事"] == event_filter]

    col1, col2, col3 = st.columns(3)
    col1.metric("參賽單位總數", view["報名單位"].nunique() if not view.empty else 0)
    col2.metric("總報名選手數", len(view))
    estimated_fee = int(view["金額"].sum()) if not view.empty and "金額" in view else 0
    col3.metric("預估總報名費", f"NT${estimated_fee:,}")

    tabs = st.tabs(["報名總表", "項目統計", "賽事設定", "權限管理"] if is_admin() else ["報名總表", "項目統計"])
    tab1, tab2 = tabs[0], tabs[1]
    with tab1:
        st.markdown("### 待核對款項")
        db = SessionLocal()
        try:
            pending_query = db.query(Registration).filter(Registration.payment_status == "待核對")
            pending_event_names = None
            if event_filter != all_label:
                pending_event_names = [event_filter]
            elif visible_event_names is not None:
                pending_event_names = visible_event_names
            if pending_event_names is not None:
                pending_query = pending_query.filter(Registration.event_name.in_(pending_event_names))
            pending_list = pending_query.all()
            if not pending_list:
                st.success("目前暫無待核對的匯款。")
            else:
                pending_df = pd.DataFrame([{
                    "賽事": p.event_name, "單位": p.team_name, "後五碼": p.pay_five_digits, "金額": p.item_amount, "教練": p.coach_name
                } for p in pending_list])
                summary_pending = pending_df.groupby(["賽事", "單位", "後五碼"]).agg({"金額":"sum"}).reset_index()
                for _, row in summary_pending.iterrows():
                    col_info, col_btn = st.columns([4, 1])
                    col_info.warning(f"【{row['賽事']}】{row['單位']} | 後五碼: {row['後五碼']} | 應對帳總金額: NT${row['金額']:,}")
                    if col_btn.button("確認已到帳", key=f"conf_{row['賽事']}_{row['單位']}"):
                        admin_confirm_payment(row['賽事'], row['單位'])
                        st.success(f"{row['單位']} 已確認收款！")
                        st.rerun()
        finally:
            db.close()
        st.divider()
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.download_button(
            "下載後台總表",
            data=dataframe_to_excel(view),
            file_name="後台報名總表.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            disabled=view.empty,
        )
        render_admin_registration_editor(view)
    with tab2:
        if view.empty:
            st.info("此賽事目前無報名資料。")
        else:
            category_summary = view.groupby(["賽事", "項目"]).size().reset_index(name="人數")
            team_summary = view.groupby("報名單位").size().reset_index(name="報名人數").sort_values("報名人數", ascending=False)
            left, right = st.columns(2)
            left.dataframe(category_summary, use_container_width=True, hide_index=True)
            right.dataframe(team_summary, use_container_width=True, hide_index=True)
            st.bar_chart(category_summary, x="項目", y="人數", color="賽事")
    if is_admin():
        with tabs[2]:
            render_event_admin()
        with tabs[3]:
            render_permission_admin()


def render_login() -> None:
    st.markdown("<div class='section-title'>登入介面</div>", unsafe_allow_html=True)
    if st.session_state.get("account"):
        st.success(f"目前帳號：{st.session_state['account']}")
        st.caption(f"權限：{role_label(current_role())}")
        st.button("登出", key="login-page-logout", on_click=logout_current_user, use_container_width=True)
        return

    render_login_box("login_page")


def main() -> None:
    inject_styles()
    ensure_default_admin_credentials()
    if not render_login_cookie_scripts():
        restore_login_from_cookie()
    apply_query_page()
    apply_pending_page_change()
    page = render_sidebar()
    page = enforce_page_access(page)
    df = db_to_dataframe(current_account())
    events = get_events()

    if page == "賽事列表":
        render_event_list(events, df)
    elif page == "競賽規程":
        render_rules(events)
    elif page == "線上報名":
        render_registration_form()
    elif page == "我的報名":
        render_my_registrations(df)
    elif page == UNIT_PAGE:
        render_profile_and_unit_page()
    elif page == ACCOUNT_PAGE:
        render_account_page()
    elif page == VISUAL_SETTINGS_PAGE:
        render_site_asset_admin()
    elif page == "管理後台":
        render_admin(
            db_to_dataframe(
                current_account(),
                include_all=True,
                event_names=admin_visible_event_names(),
            )
        )
    elif page == LOGIN_PAGE:
        render_login()
    else:
        render_login()

    st.divider()
    st.caption(f"© 2026 {site_name()}。資料僅供賽事管理與報名作業使用。")


if __name__ == "__main__":
    main()
