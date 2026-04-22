from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast

from bs4 import BeautifulSoup

from star_attendance.core.timeutils import isoformat_local, now_local
from star_attendance.login_handler import LoginHandler

logger = logging.getLogger("allowance")


@dataclass(frozen=True, slots=True)
class AllowancePeriodOption:
    period_code: str
    year: int
    label: str
    start_date: date
    end_date: date


@dataclass(frozen=True, slots=True)
class AllowancePageContext:
    allowance_url: str
    data_url: str
    tkv: str
    kv_token: str
    periods: list[AllowancePeriodOption]


class AllowanceHandler:
    def __init__(self, login_handler: LoginHandler):
        self.login_handler = login_handler
        self.base_url = login_handler.base_url
        self.client = login_handler.client

    @staticmethod
    def get_current_period_code() -> tuple[str, int]:
        now = now_local()
        day = now.day
        if day >= 15:
            start_month = now.month
            end_month = now.month + 1
            year = now.year
            if end_month > 12:
                end_month = 1
        else:
            start_month = now.month - 1
            end_month = now.month
            year = now.year
            if start_month < 1:
                start_month = 12
                year -= 1

        period_code = f"15{start_month:02d}_14{end_month:02d}"
        return period_code, year

    @staticmethod
    def get_previous_period_code() -> tuple[str, int]:
        now = now_local()
        if now.day >= 15:
            start_month = now.month - 1
            end_month = now.month
            year = now.year
        else:
            start_month = now.month - 2
            end_month = now.month - 1
            year = now.year

        if start_month < 1:
            start_month += 12
            year -= 1
        if end_month < 1:
            end_month += 12

        period_code = f"15{start_month:02d}_14{end_month:02d}"
        return period_code, year

    @classmethod
    def get_candidate_period_codes(cls) -> list[tuple[str, int]]:
        current = cls.get_current_period_code()
        previous = cls.get_previous_period_code()
        return [current] if current == previous else [current, previous]

    @staticmethod
    def is_period_unavailable_message(message: str | None) -> bool:
        normalized = str(message or "").lower()
        return "belum tersedia" in normalized and "tunjangan kinerja" in normalized

    @staticmethod
    def format_period_code(period_code: str) -> str:
        if "_" not in period_code:
            return period_code

        months = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "Mei",
            "Jun",
            "Jul",
            "Agu",
            "Sep",
            "Okt",
            "Nov",
            "Des",
        ]
        try:
            start, end = period_code.split("_")
            start_day = int(start[:2])
            start_month = int(start[2:])
            end_day = int(end[:2])
            end_month = int(end[2:])
            return f"{start_day} {months[start_month - 1]} - {end_day} {months[end_month - 1]}"
        except (ValueError, IndexError):
            return period_code

    @staticmethod
    def _build_period_window(period_code: str, year: int) -> tuple[date, date]:
        start_code, end_code = period_code.split("_", maxsplit=1)
        start_day = int(start_code[:2])
        start_month = int(start_code[2:])
        end_day = int(end_code[:2])
        end_month = int(end_code[2:])
        end_year = year + 1 if end_month < start_month else year
        return date(year, start_month, start_day), date(end_year, end_month, end_day)

    @classmethod
    def _make_period_option(cls, period_code: str, year: int, label: str | None = None) -> AllowancePeriodOption:
        start_date, end_date = cls._build_period_window(period_code, year)
        return AllowancePeriodOption(
            period_code=period_code,
            year=year,
            label=(label or cls.format_period_code(period_code)).strip(),
            start_date=start_date,
            end_date=end_date,
        )

    @classmethod
    def build_fallback_period_options(cls, year: int) -> list[AllowancePeriodOption]:
        period_codes = [
            "1501_1402",
            "1502_1403",
            "1503_1404",
            "1504_1405",
            "1505_1406",
            "1506_1407",
            "1507_1408",
            "1508_1409",
            "1509_1410",
            "1510_1411",
            "1511_1412",
            "1512_1401",
        ]
        options = [cls._make_period_option(period_code, year) for period_code in period_codes]
        return sorted(options, key=lambda item: item.start_date, reverse=True)

    @classmethod
    def _parse_period_options(cls, html: str, year: int) -> list[AllowancePeriodOption]:
        soup = BeautifulSoup(html, "html.parser")
        select = soup.find("select", id="allowance_period_code") or soup.find("select", attrs={"name": "allowance_period_code"})
        if not select:
            return cls.build_fallback_period_options(year)

        options_by_code: dict[str, AllowancePeriodOption] = {}
        for option in select.find_all("option"):
            period_code = str(option.get("value") or "").strip()
            if not period_code:
                continue
            label = " ".join(option.get_text(" ", strip=True).split())
            try:
                options_by_code[period_code] = cls._make_period_option(period_code, year, label)
            except ValueError:
                continue

        if not options_by_code:
            return cls.build_fallback_period_options(year)
        return sorted(options_by_code.values(), key=lambda item: item.start_date, reverse=True)

    @staticmethod
    def _extract_data_url(html: str, base_url: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        form = soup.find("form", id="form_input_budget__personal_allowance")
        action = str(form.get("action") or "").strip() if form else ""
        if action:
            return action if action.startswith("http") else f"{base_url}/{action.lstrip('/')}"

        uuid_match = re.search(r"/budget/personal_allowance/data/([a-z0-9-]+)", html)
        if uuid_match:
            return f"{base_url}/budget/personal_allowance/data/{uuid_match.group(1)}"
        raise ValueError("uuid_not_found")

    @staticmethod
    def _extract_tkv(html: str) -> str:
        tkv_match = re.search(r'name="tkv" value="([^"]+)"', html)
        if not tkv_match:
            tkv_match = re.search(r'var tkv = "([^"]+)"', html)
        return tkv_match.group(1) if tkv_match else ""

    @staticmethod
    def _extract_kv_token(html: str) -> str:
        token_match = re.search(r'meta name="csrf-token" content="([^"]+)"', html)
        return token_match.group(1) if token_match else ""

    @classmethod
    def _serialize_period_option(cls, option: AllowancePeriodOption) -> dict[str, Any]:
        return {
            "period_code": option.period_code,
            "year": option.year,
            "label": option.label,
            "readable_period": cls.format_period_code(option.period_code),
            "period_start": option.start_date.isoformat(),
            "period_end": option.end_date.isoformat(),
        }

    async def _fetch_allowance_page_context(
        self,
        year: int,
    ) -> tuple[AllowancePageContext | None, dict[str, Any] | None]:
        allowance_url = f"{self.base_url}/budget/personal_allowance"
        try:
            response = await self.client.get(allowance_url)
        except Exception as exc:
            logger.error(f"event=fetch_allowance status=error message='{exc}'")
            return None, {"status": "failed", "message": str(exc)}

        if response.status_code != 200:
            return None, {"status": "failed", "message": f"HTTP {response.status_code}"}

        html = response.text
        if "login" in str(response.url).lower() or "<title>login" in html.lower():
            return None, {"status": "failed", "message": "session_expired"}

        try:
            context = AllowancePageContext(
                allowance_url=allowance_url,
                data_url=self._extract_data_url(html, self.base_url),
                tkv=self._extract_tkv(html),
                kv_token=self._extract_kv_token(html),
                periods=self._parse_period_options(html, year),
            )
        except ValueError as exc:
            return None, {"status": "failed", "message": str(exc)}

        return context, None

    def _match_period_option(
        self,
        context: AllowancePageContext,
        period_code: str,
        year: int,
    ) -> AllowancePeriodOption:
        for option in context.periods:
            if option.period_code == period_code and option.year == year:
                return option
        return self._make_period_option(period_code, year)

    async def fetch_allowance_periods(self, year: int | None = None) -> dict[str, Any]:
        target_year = year or now_local().year
        context, error = await self._fetch_allowance_page_context(target_year)
        if error:
            return error
        assert context is not None
        return {
            "status": "success",
            "year": target_year,
            "periods": [self._serialize_period_option(option) for option in context.periods],
        }

    async def _post_allowance_period(
        self,
        context: AllowancePageContext,
        period_code: str,
        year: int,
    ) -> dict[str, Any]:
        boundary = "----WebKitFormBoundaryStarAsnAllowance"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="tkv"\r\n\r\n'
            f"{context.tkv}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="year"\r\n\r\n'
            f"{year}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="allowance_period_code"\r\n\r\n'
            f"{period_code}\r\n"
            f"--{boundary}--\r\n"
        )
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": context.allowance_url,
        }
        if context.kv_token:
            headers["KV-TOKEN"] = context.kv_token

        logger.info(f"event=fetch_allowance status=requesting url={context.data_url}")
        response = await self.client.post(context.data_url, data=body.encode("utf-8"), headers=headers)

        payload: dict[str, Any] | None = None
        try:
            payload = cast(dict[str, Any], response.json())
        except Exception:
            payload = None

        if response.status_code != 200:
            message = str(payload.get("message") or f"Data fetch failure: HTTP {response.status_code}") if payload else f"Data fetch failure: HTTP {response.status_code}"
            failure_stage = "period_unavailable" if self.is_period_unavailable_message(message) else "allowance_fetch_failed"
            return {
                "status": "failed",
                "message": message,
                "failure_stage": failure_stage,
                "http_status": response.status_code,
            }

        if payload is None:
            return {
                "status": "failed",
                "message": "Invalid allowance response format.",
                "failure_stage": "invalid_allowance_response",
                "http_status": response.status_code,
            }

        if str(payload.get("status") or "").lower() != "success" and "data" not in payload:
            message = str(payload.get("message") or "Data tunjangan tidak tersedia.")
            failure_stage = "period_unavailable" if self.is_period_unavailable_message(message) else "allowance_fetch_failed"
            return {
                "status": "failed",
                "message": message,
                "failure_stage": failure_stage,
                "http_status": response.status_code,
            }

        option = self._match_period_option(context, period_code, year)
        payload["period_code"] = option.period_code
        payload["year"] = option.year
        payload["period_label"] = option.label
        payload["period_start"] = option.start_date.isoformat()
        payload["period_end"] = option.end_date.isoformat()
        return payload

    async def fetch_allowance_data(self, period_code: str | None = None, year: int | None = None) -> dict[str, Any]:
        target_year = year or now_local().year
        target_period = period_code or self.get_current_period_code()[0]
        logger.info(f"event=fetch_allowance status=start period={target_period} year={target_year}")

        context, error = await self._fetch_allowance_page_context(target_year)
        if error:
            return error
        assert context is not None
        try:
            return await self._post_allowance_period(context, target_period, target_year)
        except Exception as exc:
            logger.error(f"event=fetch_allowance status=error message='{exc}'")
            return {"status": "failed", "message": str(exc)}


async def _fetch_latest_available_allowance(
    allowance_handler: AllowanceHandler,
    *,
    year: int | None = None,
) -> tuple[dict[str, Any], AllowancePeriodOption | None]:
    target_year = year or now_local().year
    last_result: dict[str, Any] = {"status": "failed", "message": "Data tunjangan tidak tersedia."}

    context, error = await allowance_handler._fetch_allowance_page_context(target_year)
    if error:
        if error.get("message") == "session_expired":
            return error, None
        context = None
        candidate_periods = [
            AllowanceHandler._make_period_option(code, candidate_year)
            for code, candidate_year in allowance_handler.get_candidate_period_codes()
        ]
    else:
        assert context is not None
        candidate_periods = context.periods

    for option in candidate_periods:
        if year is not None and option.year != target_year:
            continue

        result = (
            await allowance_handler._post_allowance_period(context, option.period_code, option.year)
            if context is not None
            else await allowance_handler.fetch_allowance_data(option.period_code, option.year)
        )
        if result.get("status") == "success" and "data" in result:
            return result, option
        if result.get("message") == "session_expired":
            return result, None

        last_result = result
        if not allowance_handler.is_period_unavailable_message(cast(str | None, result.get("message"))):
            break

    return last_result, None


def _persist_handler_session(store: Any, nip: str, handler: LoginHandler) -> None:
    cookies = handler.client.cookies.get_dict()
    if not cookies:
        return
    store.save_user_session(
        nip,
        {
            "cookies": cookies,
            "captured_at": isoformat_local(),
            "user_agent": handler.user_agent,
        },
    )


def _save_allowance_rows(
    store: Any,
    nip: str,
    payload: dict[str, Any],
    period: AllowancePeriodOption | None,
) -> None:
    data = cast(list[dict[str, Any]], payload["data"])
    resolved_period = period or AllowanceHandler._make_period_option(
        str(payload.get("period_code") or ""),
        int(payload.get("year") or now_local().year),
        str(payload.get("period_label") or "") or None,
    )
    save_user_allowance = getattr(store, "save_user_performance_allowance", None)
    if callable(save_user_allowance):
        save_user_allowance(
            nip,
            resolved_period.period_code,
            resolved_period.year,
            data,
            period_label=resolved_period.label,
            period_start=resolved_period.start_date.isoformat(),
            period_end=resolved_period.end_date.isoformat(),
        )
        return

    try:
        store.save_personal_allowance(
            nip,
            resolved_period.period_code,
            data,
            year=resolved_period.year,
            period_label=resolved_period.label,
            period_start=resolved_period.start_date.isoformat(),
            period_end=resolved_period.end_date.isoformat(),
        )
    except TypeError:
        store.save_personal_allowance(nip, resolved_period.period_code, data)


async def list_user_allowance_periods(nip: str, year: int | None = None) -> dict[str, Any]:
    from star_attendance.runtime import get_store

    store = get_store()
    user_cred = store.get_user_data(nip)
    if not user_cred:
        return {"status": "failed", "message": "User data not found."}

    password = user_cred.get("password")
    proxy = cast(str | None, user_cred.get("proxy"))
    handler = LoginHandler(proxy=proxy)

    try:
        session_data = store.get_user_session(nip)
        if session_data and "cookies" in session_data:
            for name, value in session_data["cookies"].items():
                handler.client.cookies.set(name, value, domain="star-asn.kemenimipas.go.id")

            allowance_handler = AllowanceHandler(handler)
            result = await allowance_handler.fetch_allowance_periods(year)
            if result.get("status") == "success":
                return result
            if result.get("message") != "session_expired":
                return result

        if not password:
            return {"status": "failed", "message": "Password is required for session recovery."}

        login_res = await handler.login(nip, password)
        if login_res.get("status") != "success":
            return {"status": "failed", "message": f"Login failed: {login_res.get('message')}"}

        _persist_handler_session(store, nip, handler)
        allowance_handler = AllowanceHandler(handler)
        return await allowance_handler.fetch_allowance_periods(year)
    finally:
        await handler.client.close()


async def sync_user_allowance(
    nip: str,
    *,
    period_code: str | None = None,
    year: int | None = None,
) -> dict[str, Any]:
    """
    Syncs user allowance data directly from the portal and stores it by user/periode.
    """
    from star_attendance.runtime import get_store

    store = get_store()
    user_cred = store.get_user_data(nip)
    if not user_cred:
        return {"status": "failed", "message": "User data not found."}

    password = user_cred.get("password")
    proxy = cast(str | None, user_cred.get("proxy"))
    handler = LoginHandler(proxy=proxy)

    async def fetch_with_handler() -> tuple[dict[str, Any], AllowancePeriodOption | None]:
        allowance_handler = AllowanceHandler(handler)
        if period_code:
            result = await allowance_handler.fetch_allowance_data(period_code, year)
            if result.get("status") == "success" and "data" in result:
                selected_period = AllowanceHandler._make_period_option(
                    str(result.get("period_code") or period_code),
                    int(result.get("year") or year or now_local().year),
                    str(result.get("period_label") or "") or None,
                )
                return result, selected_period
            return result, None
        return await _fetch_latest_available_allowance(allowance_handler, year=year)

    try:
        session_data = store.get_user_session(nip)
        if session_data and "cookies" in session_data:
            for name, value in session_data["cookies"].items():
                handler.client.cookies.set(name, value, domain="star-asn.kemenimipas.go.id")

            result, selected_period = await fetch_with_handler()
            if result.get("status") == "success" and selected_period and "data" in result:
                _persist_handler_session(store, nip, handler)
                _save_allowance_rows(store, nip, result, selected_period)
                return {
                    "status": "success",
                    "period": selected_period.period_code,
                    "year": selected_period.year,
                    "count": len(cast(list[dict[str, Any]], result["data"])),
                }
            if result.get("message") != "session_expired":
                return result

        if not password:
            return {"status": "failed", "message": "Password is required for session recovery."}

        login_res = await handler.login(nip, password)
        if login_res.get("status") != "success":
            return {"status": "failed", "message": f"Login failed: {login_res.get('message')}"}

        _persist_handler_session(store, nip, handler)
        result, selected_period = await fetch_with_handler()
        if result.get("status") == "success" and selected_period and "data" in result:
            _save_allowance_rows(store, nip, result, selected_period)
            return {
                "status": "success",
                "period": selected_period.period_code,
                "year": selected_period.year,
                "count": len(cast(list[dict[str, Any]], result["data"])),
            }
        return result
    finally:
        await handler.client.close()
