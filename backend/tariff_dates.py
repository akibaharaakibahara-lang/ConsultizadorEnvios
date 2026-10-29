from datetime import date, datetime


def parse_tariff_date(value: str | None) -> date | None:
    if value is None or not value.strip():
        return None

    normalized = value.strip()
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        try:
            return datetime.strptime(normalized, "%m-%d-%Y").date()
        except ValueError as exc:
            raise ValueError(
                f"Formato de vigencia de tarifa no válido: {value}"
            ) from exc


def select_applicable_tariffs(tariffs, weight: float, today: date):
    eligible = [
        tariff
        for tariff in tariffs
        if float(tariff.peso_min) <= weight < float(tariff.peso_max)
        and (
            parse_tariff_date(tariff.vigencia_desde) is None
            or parse_tariff_date(tariff.vigencia_desde) <= today
        )
    ]
    if not eligible:
        return []

    latest_effective_date = max(
        parse_tariff_date(tariff.vigencia_desde) or date.min
        for tariff in eligible
    )
    return [
        tariff
        for tariff in eligible
        if (parse_tariff_date(tariff.vigencia_desde) or date.min)
        == latest_effective_date
    ]
