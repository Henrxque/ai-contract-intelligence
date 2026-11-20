import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from app.models import FIELD_SPECS, Evidence, Extraction, Finding, ReviewField, SourcePage


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
DATE_PATTERN = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|"
    r"\d{1,2}\s+(?:de\s+)?[A-Za-zç]+\s+(?:de\s+)?\d{4}|"
    r"[A-Za-z]+\s+\d{1,2},?\s+\d{4})\b",
    re.I,
)


def parse_date(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value).isoformat()
    slash = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if slash:
        first, second, year = map(int, slash.groups())
        if first <= 12 and second <= 12 and first != second:
            raise ValueError(
                "Ambiguous date: both day/month and month/day are possible. Use an explicit month or ISO date."
            )
        day, month = (first, second) if first > 12 else (second, first)
        return date(year, month, day).isoformat()
    tokens = re.sub(r"\bde\b|,", " ", value.casefold()).split()
    if len(tokens) == 3:
        if tokens[0] in MONTHS:
            month, day, year = MONTHS[tokens[0]], int(tokens[1]), int(tokens[2])
        else:
            day, month, year = int(tokens[0]), MONTHS[tokens[1]], int(tokens[2])
        return date(year, month, day).isoformat()
    raise ValueError("Date format could not be validated. Use YYYY-MM-DD or a spelled-out month.")


def parse_amount(value: str) -> str:
    value = re.sub(r"(?:USD|EUR|GBP|BRL|CAD|AUD|R\$|US\$|[$€£])", "", value, flags=re.I).strip()
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+\.\d{1,2}", value):
        value = value.replace(",", "")
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+,\d{1,2}", value):
        value = value.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d+,\d{1,2}", value):
        value = value.replace(",", ".")
    if not re.fullmatch(r"-?\d+(?:\.\d{1,2})?", value):
        raise ValueError(
            "Amount is ambiguous or invalid. Use a decimal amount with at most two decimal places."
        )
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount < 0 or amount > Decimal("999999999999999.99"):
            raise ValueError("Amount must be non-negative and at most 999,999,999,999,999.99.")
        return f"{amount:.2f}"
    except InvalidOperation as exc:
        raise ValueError("Amount could not be validated.") from exc


CURRENCY_CODES = set(
    "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BOV BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW UZS VED VES VND VUV WST XAF XCD XOF XPF YER ZAR ZMW ZWG".split()
)
CURRENCY_NAMES = {
    "us dollars": "USD",
    "us dollar": "USD",
    "u.s. dollars": "USD",
    "euros": "EUR",
    "euro": "EUR",
    "brazilian reais": "BRL",
    "reais": "BRL",
    "pounds sterling": "GBP",
}


def normalize_currency(value: str) -> str:
    code = CURRENCY_NAMES.get(value.strip().casefold(), value.strip().upper())
    if code not in CURRENCY_CODES:
        raise ValueError(
            "Currency must be an explicit recognized ISO code or an unambiguous currency name; '$' alone is insufficient."
        )
    return code


def value_supported(key: str, value: str, evidence: list[Evidence]) -> bool:
    for item in evidence:
        if key in {"effective_date", "end_date"}:
            for match in DATE_PATTERN.finditer(item.quote):
                try:
                    if parse_date(match.group()) == value:
                        return True
                except (ValueError, KeyError):
                    continue
        elif key == "total_value":
            for match in re.finditer(r"(?<![\w.])[-+]?\d[\d.,]*(?![\w.])", item.quote):
                try:
                    if parse_amount(match.group().rstrip(".,")) == value:
                        return True
                except ValueError:
                    continue
        elif key == "currency":
            if re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", item.quote, re.I):
                return True
            if any(
                code == value and re.search(r"\b" + re.escape(name) + r"\b", item.quote, re.I)
                for name, code in CURRENCY_NAMES.items()
            ):
                return True
        elif normalize(value) in normalize(item.quote):
            return True
    return False


def validate_extraction(
    extraction: Extraction, pages: list[SourcePage]
) -> tuple[list[ReviewField], list[Finding]]:
    source = {page.number: normalize(page.text) for page in pages}
    fields = []
    findings = []
    for key, (label, group, required) in FIELD_SPECS.items():
        raw = getattr(extraction.fields, key)
        value = raw.value.strip() if raw.value and raw.value.strip() else None
        status = "supported"
        issues = []
        codes = []
        evidence = raw.evidence
        if value is None:
            status = "missing"
            issues.append(raw.reason or "No explicit value was extracted from the document.")
            codes.append("missing_required" if required else "missing_optional")
        else:
            try:
                if key in {"effective_date", "end_date"}:
                    value = parse_date(value)
                elif key == "total_value":
                    value = parse_amount(value)
                elif key == "currency":
                    value = normalize_currency(value)
            except (ValueError, KeyError) as exc:
                status = "uncertain" if "ambiguous date" in str(exc).lower() else "invalid"
                issues.append(
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "Month name could not be recognized."
                )
                codes.append("invalid_format")
            grounded = bool(evidence) and all(
                normalize(e.quote) in source.get(e.page, "") for e in evidence
            )
            if not grounded:
                if status != "invalid":
                    status = "uncertain"
                issues.append(
                    "Evidence is missing or its quote/page could not be matched to the PDF text."
                )
                codes.append("unverified_evidence")
            elif status == "supported" and not value_supported(key, value, evidence):
                status = "uncertain"
                issues.append(
                    "The quoted source does not directly support this value. A reviewer must check the interpretation."
                )
                codes.append("unsupported_value")
            if raw.uncertain:
                if status != "invalid":
                    status = "uncertain"
                issues.append(
                    raw.reason or "The extractor flagged conflicting or ambiguous wording."
                )
                codes.append("extractor_uncertain")
        field = ReviewField(
            key=key,
            label=label,
            group=group,
            required=required,
            value=value,
            evidence=evidence,
            status=status,
            issues=issues,
        )
        fields.append(field)
        for code, message in zip(codes, issues, strict=True):
            severity = (
                "error"
                if status == "invalid" or (status == "missing" and required)
                else "info"
                if status == "missing"
                else "warning"
            )
            findings.append(Finding(field=key, severity=severity, code=code, message=message))
    by_key = {field.key: field for field in fields}
    start, end = by_key["effective_date"], by_key["end_date"]
    if start.status == "supported" and end.status == "supported" and end.value < start.value:
        end.status = "invalid"
        message = "The end date precedes the effective date. Review the dates in the source."
        end.issues.append(message)
        findings.append(
            Finding(field="end_date", severity="error", code="date_order", message=message)
        )
    return fields, findings
