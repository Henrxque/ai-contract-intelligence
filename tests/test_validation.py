import pytest

from app.errors import AnalysisError
from app.extractors import extract_local
from app.models import Evidence, SourcePage
from app.validation import parse_amount, parse_date, validate_extraction


def check(text, mutate=None):
    pages = [SourcePage(number=1, text=text)]
    extraction = extract_local(pages)
    if mutate:
        mutate(extraction)
    fields, findings = validate_extraction(extraction, pages)
    return {f.key: f for f in fields}, findings


@pytest.mark.parametrize(
    "value,expected",
    [
        ("48,000.00", "48000.00"),
        ("48.000,00", "48000.00"),
        ("R$ 1250,50", "1250.50"),
        ("0", "0.00"),
        ("USD 200.00", "200.00"),
    ],
)
def test_decimal_amounts(value, expected):
    assert parse_amount(value) == expected


@pytest.mark.parametrize(
    "value",
    ["NaN", "Infinity", "-10.00", "1.234", "12,000", "100 or 200", "1e10", "99999999999999999"],
)
def test_invalid_and_ambiguous_amounts(value):
    with pytest.raises(ValueError):
        parse_amount(value)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-12-15", "2026-12-15"),
        ("15 December 2026", "2026-12-15"),
        ("December 15, 2026", "2026-12-15"),
        ("15 de dezembro de 2026", "2026-12-15"),
        ("15/12/2026", "2026-12-15"),
        ("12/15/2026", "2026-12-15"),
    ],
)
def test_date_normalization(value, expected):
    assert parse_date(value) == expected


@pytest.mark.parametrize("value", ["2026-02-30", "01/02/2026", "2026-13-01"])
def test_ambiguous_or_impossible_dates(value):
    with pytest.raises(ValueError):
        parse_date(value)


def test_missing_required_fields_and_null_placeholder():
    fields, findings = check("Client: Acme Inc.\nEnd date: TBD")
    assert fields["end_date"].value is None
    assert fields["party_a"].status == "missing"
    assert any(f.code == "missing_required" and f.field == "party_a" for f in findings)
    assert fields["governing_law"].status == "missing"
    assert next(f for f in findings if f.field == "governing_law").severity == "info"


def test_conflicting_values_are_not_silently_accepted():
    fields, _ = check("Payment terms: Net 15 days.\nPayment terms: Net 60 days.")
    assert fields["payment_terms"].status == "uncertain"
    assert len(fields["payment_terms"].evidence) == 2


def test_possible_multiline_qualification_is_flagged():
    fields, _ = check("Payment terms: Invoices are due in 30 days\nunless disputed in writing.")
    assert fields["payment_terms"].status == "uncertain"
    assert "continuation" in fields["payment_terms"].issues[0]


def test_very_long_local_field_has_actionable_error():
    with pytest.raises(AnalysisError) as exc:
        extract_local([SourcePage(number=1, text="Client: " + "A" * 4001)])
    assert exc.value.code == "local_field_too_long"


def test_date_order_is_invalid():
    fields, findings = check("Effective date: 2026-06-01\nEnd date: 2026-01-01")
    assert fields["end_date"].status == "invalid"
    assert any(f.code == "date_order" for f in findings)


@pytest.mark.parametrize(
    "kind", ["fabricated_quote", "wrong_page", "unsupported_value", "no_evidence"]
)
def test_model_evidence_must_be_grounded(kind):
    def mutate(extraction):
        field = extraction.fields.party_b
        if kind == "fabricated_quote":
            field.evidence = [Evidence(page=1, quote="Client: Imaginary Corp.")]
        elif kind == "wrong_page":
            field.evidence[0].page = 2
        elif kind == "unsupported_value":
            field.value = "Imaginary Corp."
        else:
            field.evidence = []

    fields, _ = check("Client: Acme Inc.", mutate)
    assert fields["party_b"].status == "uncertain"


def test_normalized_model_amount_requires_exact_numeric_evidence():
    def mutate(extraction):
        extraction.fields.total_value.value = "100.00"

    fields, _ = check("Contract value: 1000.00", mutate)
    assert fields["total_value"].status == "uncertain"


def test_currency_cannot_be_inferred_from_symbol():
    fields, _ = check("Currency: $")
    assert fields["currency"].status == "invalid"


def test_portuguese_labels_and_explicit_dates():
    fields, _ = check(
        "Contratada: Empresa Exemplo Ltda.\nContratante: Cliente Fictício Ltda.\nData de início: 15 de dezembro de 2026\nValor total: 1.500,00\nMoeda: BRL"
    )
    assert fields["party_a"].status == "supported"
    assert fields["effective_date"].value == "2026-12-15"
    assert fields["effective_date"].status == "supported"
    assert fields["total_value"].value == "1500.00"
    assert fields["total_value"].status == "supported"
