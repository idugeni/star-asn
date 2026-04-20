from enum import Enum

class UserRole(str, Enum):
    admin = "admin"
    user = "user"
    system = "system"

class AuditStatus(str, Enum):
    success = "success"
    failed = "failed"
    error = "error"
    pending = "pending"
    skipped = "skipped"
    ok = "ok"

class AuditAction(str, Enum):
    login = "login"
    logout = "logout"
    checkin = "checkin"
    checkout = "checkout"
    registration = "registration"
    update_profile = "update_profile"
    scheduler_sync = "scheduler_sync"
    settings_update = "settings_update"
    delete_personnel = "delete_personnel"
    search = "search"
    broadcast = "broadcast"
    abort = "abort"
    in_ = "in"
    out = "out"
    other = "other"

class RuleMode(str, Enum):
    smart = "smart"
    manual = "manual"
    hybrid = "hybrid"

class WorkdayPreset(str, Enum):
    mon_fri = "mon-fri"
    mon_sat = "mon-sat"
    everyday = "everyday"
