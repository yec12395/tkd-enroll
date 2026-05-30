from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text

from database import Base

Base.registry.dispose()
Base.metadata.clear()


class Registration(Base):
    __tablename__ = "registrations"

    id = Column(Integer, primary_key=True)
    account_email = Column(String, index=True)
    event_name = Column(String)
    team_name = Column(String)
    leader_name = Column(String)
    coach_name = Column(String)
    manager_name = Column(String)
    athlete_name = Column(String)
    gender = Column(String)
    birth_date = Column(String)
    category = Column(String)
    group_name = Column(String)
    rank_level = Column(String)
    level = Column(String)
    item_amount = Column(Integer)
    note = Column(String)
    phone = Column(String)
    payment_status = Column(String, default="未繳費")
    pay_five_digits = Column(String)
    pay_remark = Column(String)


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True)
    account_email = Column(String, unique=True, index=True)
    name = Column(String)
    phone = Column(String)
    role = Column(String, default="coach")


class SiteAsset(Base):
    __tablename__ = "site_assets"

    id = Column(Integer, primary_key=True)
    asset_key = Column(String, unique=True, index=True)
    filename = Column(String)
    content_type = Column(String)
    data_base64 = Column(Text)


class TeamUnit(Base):
    __tablename__ = "team_units"

    id = Column(Integer, primary_key=True)
    account_email = Column(String, index=True)
    unit_name = Column(String)


class StaffMember(Base):
    __tablename__ = "staff_members"

    id = Column(Integer, primary_key=True)
    account_email = Column(String, index=True)
    unit_id = Column(Integer, ForeignKey("team_units.id"))
    role = Column(String)
    name = Column(String)
    phone = Column(String)


class CompetitionEvent(Base):
    __tablename__ = "competition_events"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, index=True)
    city = Column(String)
    status = Column(String)
    registration_start = Column(String)
    date = Column(String)
    deadline = Column(String)
    venue = Column(String)
    host = Column(String)
    description = Column(String)
    pdf_url = Column(String)


class EventItem(Base):
    __tablename__ = "event_items"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("competition_events.id"), index=True)
    name = Column(String)
    amount = Column(Integer)


class EventGroup(Base):
    __tablename__ = "event_groups"

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("event_items.id"), index=True)
    name = Column(String)


class EventLevel(Base):
    __tablename__ = "event_levels"

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("event_groups.id"), index=True)
    name = Column(String)
