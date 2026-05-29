from datetime import date, datetime, time, timedelta
from html import escape
from io import BytesIO
import os

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from database import Base, SessionLocal, engine
from models import (
    CompetitionEvent,
    EventGroup,
    EventItem,
    EventLevel,
    Registration,
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

Base.metadata.create_all(bind=engine)

ADMIN_ACCESS_CODE = "admin2026"


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


st.set_page_config(
    page_title="跆拳道賽事報名系統",
    page_icon="賽",
    layout="wide",
    initial_sidebar_state="expanded",
)


EVENTS = [
    {
        "name": "桃園市航空盃跆拳道賽",
        "city": "桃園市",
        "status": "熱烈報名中",
        "date": "2026-07-18",
        "deadline": "2026-06-25 23:59",
        "venue": "桃園市立體育館",
        "host": "桃園市體育總會跆拳道委員會",
        "fee": 900,
        "description": "開放對打、品勢、競速踢擊項目，採線上報名與名單匯出作業。",
    },
    {
        "name": "暑期跆拳道挑戰賽",
        "city": "新北市",
        "status": "即將開放",
        "date": "2026-08-09",
        "deadline": "2026-07-12 23:59",
        "venue": "新莊體育館",
        "host": "韻動國際",
        "fee": 800,
        "description": "適合初階與進階選手參與，含個人賽與團體推廣賽。",
    },
    {
        "name": "品勢邀請賽",
        "city": "台中市",
        "status": "報名已截止",
        "date": "2026-06-14",
        "deadline": "2026-05-20 23:59",
        "venue": "台中市朝馬國民運動中心",
        "host": "全國品勢推廣協會",
        "fee": 700,
        "description": "重視禮儀、技術穩定度與競賽節奏，提供完整核對名單。",
    },
]

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
PAGE_ALIASES = {"個人與單位": UNIT_PAGE, "系統登入": LOGIN_PAGE}
NAV_PAGES = ["賽事列表", "我的報名", UNIT_PAGE, LOGIN_PAGE]
PAGES = NAV_PAGES + ["競賽規程", "線上報名", "管理後台", ACCOUNT_PAGE]
ADMIN_ONLY_PAGES = {"管理後台"}
PROFILE_SECTIONS = ["參賽單位", "隊職員名單"]


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


def request_page_change(page: str) -> None:
    page = PAGE_ALIASES.get(page, page)
    st.session_state["pending_page"] = page
    if page in NAV_PAGES:
        st.session_state["nav_page"] = page


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


def go_to_account_page() -> None:
    request_page_change(ACCOUNT_PAGE)


def go_to_admin_page() -> None:
    request_page_change("管理後台")


def select_nav_page() -> None:
    st.session_state["page"] = st.session_state["nav_page"]
    st.session_state.pop("pending_page", None)


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
            max-width: 92px;
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
            min-height: 268px;
            box-shadow: var(--shadow);
            border-top: 4px solid var(--brand);
        }

        .event-card h3 {
            margin: .85rem 0 .55rem;
            color: var(--navy);
            font-size: 1.18rem;
            line-height: 1.35;
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
            margin-top: .85rem;
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
            .summary-strip {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def db_to_dataframe(account_email: str | None = None, include_all: bool = False) -> pd.DataFrame:
    db = SessionLocal()
    try:
        query = db.query(Registration)
        if account_email and not include_all:
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
        return pd.DataFrame(rows)
    finally:
        db.close()


def dataframe_to_excel(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="報名名單")
    return buffer.getvalue()


def current_account() -> str | None:
    return st.session_state.get("account")


def current_role() -> str:
    account = current_account()
    profile = get_user_profile(account)
    return (profile.role if profile and profile.role else "coach")


def is_admin() -> bool:
    return current_role() == "admin"


def visible_pages() -> list[str]:
    return NAV_PAGES


def can_access_page(page: str) -> bool:
    return page not in ADMIN_ONLY_PAGES or is_admin()


def enforce_page_access(page: str) -> str:
    if can_access_page(page):
        return page

    st.session_state["page"] = "賽事列表"
    st.session_state.pop("pending_page", None)
    st.warning("管理後台僅限管理員使用，已為你切回賽事列表。")
    return "賽事列表"


def ensure_user_account(account_email: str, role: str = "coach") -> None:
    db = SessionLocal()
    try:
        profile = db.query(UserProfile).filter(UserProfile.account_email == account_email).first()
        if profile is None:
            profile = UserProfile(account_email=account_email, role=role)
            db.add(profile)
        elif role == "admin":
            profile.role = "admin"
        elif not profile.role:
            profile.role = "coach"
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
            profile = UserProfile(account_email=account_email, role="coach")
            db.add(profile)
        elif not profile.role:
            profile.role = "coach"
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
                st.markdown(
                    f"""
                    <div class="event-card">
                        <span class="badge {event_status_class(event['status'])}">{event['status']}</span>
                        <h3>{event['name']}</h3>
                        <p class="event-description">{event['description']}</p>
                        <div class="event-meta">
                            <div><span>比賽日期</span><strong>{event['date']}</strong></div>
                            <div><span>比賽地點</span><strong>{event['venue']}</strong></div>
                            <div><span>報名截止</span><strong>{event['deadline']}</strong></div>
                            <div><span>報名費用</span><strong>NT${event['fee']:,}</strong></div>
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

    st.markdown(
        f"""
        <section class="hero">
            <h1>跆拳道賽事報名系統</h1>
            <div class="hero-stats">
                <div class="stat"><strong>{len(events)}</strong><span>目前賽事</span></div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> str:
    with st.sidebar:
        logo_path = brand_logo_path()
        if logo_path:
            st.image(logo_path, width=96)
        st.markdown(
            """
            <div class="sidebar-brand">
                <div>
                    <strong>賽事報名網</strong>
                    <span>跆拳道賽事報名平台</span>
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
        )
        st.divider()
        if st.session_state.get("account"):
            role_label = "管理員" if is_admin() else "教練"
            st.success(f"已登入（{role_label}）")
            st.button(
                f"帳號：{st.session_state['account']}",
                key="sidebar-account-button",
                on_click=go_to_account_page,
                use_container_width=True,
            )
            if is_admin():
                st.button(
                    "管理後台",
                    key="sidebar-admin-button",
                    on_click=go_to_admin_page,
                    use_container_width=True,
                )
            if not get_user_profile(st.session_state["account"]):
                st.warning("請先建立聯絡人資料")
        else:
            st.warning("尚未登入")
        st.divider()
        st.caption("建議使用 Chrome、Edge 或 Safari 開啟，避免內建瀏覽器登入受限。")
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
        <div class="info-panel">
            <h3>登入後才能進行報名</h3>
            <p>請先登入帳號，系統會用此帳號保存與查詢你的報名資料。</p>
            <p class="small-note">正式上線時可改串 Google OAuth；目前先用 Email 作為測試登入。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    account = st.text_input("Email", placeholder="demo@example.com", key=f"{prefix}_email")
    if st.button("登入", key=f"{prefix}_button", use_container_width=True):
        if account.strip():
            ensure_user_account(account.strip(), "coach")
            st.session_state["account"] = account.strip()
            if prefix in {"rules", "registration"} and st.session_state.get("selected_event_name"):
                route_to_registration_or_unit_setup()
            else:
                request_page_change(UNIT_PAGE)
            st.rerun()
        st.warning("請輸入 Email。")


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

    st.caption(f"目前登入帳號：{account}")
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


def render_admin(df: pd.DataFrame) -> None:
    st.markdown("<div class='section-title'>管理後台</div>", unsafe_allow_html=True)
    if not is_admin():
        st.error("此頁僅限後台管理員使用。")
        return

    events = get_events()
    event_filter = st.selectbox("請選擇要查看的賽事", ["全部賽事"] + [event["name"] for event in events])
    view = df if event_filter == "全部賽事" or df.empty else df[df["賽事"] == event_filter]

    col1, col2, col3 = st.columns(3)
    col1.metric("參賽單位總數", view["報名單位"].nunique() if not view.empty else 0)
    col2.metric("總報名選手數", len(view))
    estimated_fee = int(view["金額"].sum()) if not view.empty and "金額" in view else 0
    col3.metric("預估總報名費", f"NT${estimated_fee:,}")

    tab1, tab2, tab3 = st.tabs(["報名總表", "項目統計", "賽事設定"])
    # 在 render_admin 的 with tab1: 最上方加入
    with tab1:
        st.markdown("### 🔍 智能查帳審核面板 (待核對款項)")
        db = SessionLocal()
        try:
            pending_list = db.query(Registration).filter(Registration.payment_status == "待核對").all()
            if not pending_list:
                st.success("目前暫無待核對的匯款。")
            else:
                # 依單位群組顯示
                pending_df = pd.DataFrame([{
                    "賽事": p.event_name, "單位": p.team_name, "後五碼": p.pay_five_digits, "金額": p.item_amount, "教練": p.coach_name
                } for p in pending_list])
                
                summary_pending = pending_df.groupby(["賽事", "單位", "後五碼"]).agg({"金額":"sum"}).reset_index()
                
                for _, row in summary_pending.iterrows():
                    col_info, col_btn = st.columns([4, 1])
                    col_info.warning(f"🔔 【{row['賽事']}】{row['單位']} | 後五碼: {row['後五碼']} | 應對帳總金額: NT${row['金額']:,}")
                    if col_btn.button("確認已到帳", key=f"conf_{row['賽事']}_{row['單位']}"):
                        admin_confirm_payment(row['賽事'], row['單位'])
                        st.success(f"{row['單位']} 已確認收款！")
                        st.rerun()
        finally:
            db.close()
        st.divider()
    with tab1:
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.download_button(
            "下載後台總表",
            data=dataframe_to_excel(view),
            file_name="後台報名總表.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            disabled=view.empty,
        )
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
    with tab3:
        render_event_admin()


def render_login() -> None:
    st.markdown("<div class='section-title'>登入介面</div>", unsafe_allow_html=True)
    col1, col2 = st.columns([1.2, 1])
    with col1:
        st.markdown(
            """
            <div class="info-panel">
                <h3>Google 帳號登入</h3>
                <p>正式上線時可串接 Google OAuth，讓參賽單位管理自己的報名資料，主辦方則可進入管理後台。</p>
                <p class="small-note">LINE 或 Facebook 內建瀏覽器可能會阻擋 Google 登入，建議使用系統瀏覽器開啟。</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        account = st.text_input("測試帳號 Email", placeholder="demo@example.com")
        admin_code = st.text_input("管理員代碼（選填）", type="password")
        if st.button("使用測試帳號登入", use_container_width=True):
            if account.strip():
                role = "admin" if admin_code.strip() == ADMIN_ACCESS_CODE else "coach"
                ensure_user_account(account.strip(), role)
                st.session_state["account"] = account.strip()
                request_page_change("管理後台" if role == "admin" else UNIT_PAGE)
                st.success(f"已登入：{account.strip()}")
                st.rerun()
            else:
                st.warning("請輸入 Email。")
        if st.session_state.get("account"):
            st.info(f"目前帳號：{st.session_state['account']}")


def main() -> None:
    inject_styles()
    apply_pending_page_change()
    page = render_sidebar()
    page = enforce_page_access(page)
    df = db_to_dataframe(current_account(), include_all=is_admin())
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
    elif page == "管理後台":
        render_admin(df)
    elif page == LOGIN_PAGE:
        render_login()
    else:
        render_login()

    st.divider()
    st.caption("© 2026 跆拳道賽事報名系統。資料僅供賽事管理與報名作業使用。")


if __name__ == "__main__":
    main()
