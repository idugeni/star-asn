import uuid
from typing import Any

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship

from star_attendance.core.timeutils import now_storage
from star_attendance.db.enums import AuditAction, AuditStatus, UserRole, WorkdayPreset


class Base(DeclarativeBase):
    pass


class UPT(Base):
    __tablename__ = "upts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nama_upt = Column(String(255), nullable=False, unique=True)
    timezone = Column(String(50), default="Asia/Jakarta")

    users = relationship("User", back_populates="upt")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nip = Column(String(50), unique=True, index=True, nullable=False)
    nama = Column(String(255), nullable=False)
    password = Column(Text, nullable=True)
    upt_id = Column(UUID(as_uuid=True), ForeignKey("upts.id"), nullable=True)

    telegram_id = Column(BigInteger, unique=True, nullable=True, index=True)
    cron_in = Column(String(10), nullable=True)
    cron_out = Column(String(10), nullable=True)
    workdays: Any = Column(
        Enum(WorkdayPreset, name="workday_preset", values_callable=lambda x: [e.value for e in x]), nullable=True
    )

    # Security & RLS
    role: Any = Column(
        Enum(UserRole, name="user_role", create_type=False, values_callable=lambda x: [e.value for e in x]),
        default=UserRole.user,
    )
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    personal_latitude = Column(Float, nullable=True)
    personal_longitude = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), default=now_storage)
    updated_at = Column(DateTime(timezone=True), default=now_storage, onupdate=now_storage)

    upt = relationship("UPT", back_populates="users")
    logs = relationship("AuditLog", back_populates="user")
    session = relationship("UserSession", back_populates="user", uselist=False, cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    nip = Column(String(50), nullable=True)
    data = Column(JSONB, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now_storage, onupdate=now_storage)

    user = relationship("User", back_populates="session")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    nip = Column(String(50), nullable=False, index=True)
    action: Any = Column(
        Enum(AuditAction, name="audit_action", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    status: Any = Column(
        Enum(AuditStatus, name="audit_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    message = Column(Text)
    response_time = Column(Float, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=now_storage, index=True)

    user = relationship("User", back_populates="logs")


class GlobalSetting(Base):
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text)
    description = Column(String(255))


class PersonalAllowance(Base):
    __tablename__ = "personal_allowances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    nip = Column(String(50), nullable=False, index=True)
    date = Column(DateTime(timezone=True), nullable=False, index=True)
    clock_in = Column(String(20))
    clock_out = Column(String(20))
    daily_allowance_amount = Column(String(50))
    deduction_amount = Column(String(50))
    total = Column(String(50))
    deduction_reason = Column(Text, nullable=True)
    period_code = Column(String(20), index=True)
    updated_at = Column(DateTime(timezone=True), default=now_storage, onupdate=now_storage)

    user = relationship("User")


class UserPerformanceAllowance(Base):
    __tablename__ = "user_performance_allowances"
    __table_args__ = (
        UniqueConstraint(
            "nip",
            "allowance_year",
            "period_code",
            "allowance_date",
            name="uq_user_performance_allowances_period_day",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    nip = Column(String(50), nullable=False, index=True)
    allowance_year = Column(Integer, nullable=False, index=True)
    period_code = Column(String(20), nullable=False, index=True)
    period_label = Column(String(80), nullable=True)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    allowance_date = Column(Date, nullable=False, index=True)
    clock_in = Column(String(20))
    clock_out = Column(String(20))
    daily_allowance_amount = Column(String(50))
    deduction_amount = Column(String(50))
    total = Column(String(50))
    deduction_reason = Column(Text, nullable=True)
    raw_payload = Column(JSONB, nullable=True)
    synced_at = Column(DateTime(timezone=True), default=now_storage, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now_storage, onupdate=now_storage, nullable=False)

    user = relationship("User")
