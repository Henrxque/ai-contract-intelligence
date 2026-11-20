"""Author synthetic stress PDFs and independent expected answers; never call an extractor."""

import hashlib
import json
from pathlib import Path

from generate_samples import DESTINATION, make_pdf

ROOT = Path(__file__).resolve().parents[1]
BASE = {
    "party_a": "Meridian Data Works Ltd.",
    "party_b": "Harbor Retail Group Inc.",
    "effective_date": "2026-01-15",
    "end_date": "2026-12-31",
    "total_value": "72000.00",
    "currency": "USD",
    "payment_terms": "Invoices are payable within 30 days of receipt.",
    "governing_law": "Laws of England and Wales.",
    "termination": "Either party may terminate with 60 days written notice.",
    "confidentiality": "Non-public information must remain confidential for two years.",
    "liability": "Aggregate liability is capped at the total fees paid.",
}
commercial = [
    "Service provider: Meridian Data Works Ltd.",
    "Client: Harbor Retail Group Inc.",
    "Effective date: 2026-01-15",
    "End date: 2026-12-31",
    "Contract value: 72,000.00",
    "Currency: USD",
    "Payment terms: Invoices are payable within 30 days of receipt.",
]
clauses = [
    "Governing law: Laws of England and Wales.",
    "Termination: Either party may terminate with 60 days written notice.",
    "Confidentiality: Non-public information must remain confidential for two years.",
    "Liability: Aggregate liability is capped at the total fees paid.",
]


def case(filename, values, statuses=None, notes=""):
    return {
        "filename": filename,
        "sha256": hashlib.sha256((DESTINATION / filename).read_bytes()).hexdigest(),
        "expected_values": values,
        "expected_statuses": {
            key: (statuses or {}).get(key, "missing" if value is None else "supported")
            for key, value in values.items()
        },
        "notes": notes,
    }


if __name__ == "__main__":
    make_pdf(
        "portuguese-agreement.pdf",
        "Aurora - Contrato de Servicos",
        [
            "Contratada: Aurora Dados Ltda.",
            "Contratante: Horizonte Comercio Ltda.",
            "Data de inicio: 15 de janeiro de 2026",
            "Data de termino: 31 de dezembro de 2026",
            "Valor total: 1.500,00",
            "Moeda: BRL",
            "Condicoes de pagamento: Pagamento em ate 15 dias do recebimento.",
        ],
        [
            "Lei aplicavel: Leis da Republica Federativa do Brasil.",
            "Rescisao: Qualquer parte pode rescindir mediante aviso de 30 dias.",
            "Confidencialidade: As partes devem proteger informacoes confidenciais.",
            "Responsabilidade: Limitada ao total de honorarios pagos.",
        ],
    )
    make_pdf(
        "prose-agreement.pdf",
        "Meridian - Narrative Agreement",
        [
            "Meridian Data Works Ltd. is the service provider under this agreement.",
            "Harbor Retail Group Inc. is the client under this agreement.",
            "Services begin on January 15, 2026 and end on December 31, 2026.",
            "The total contract value is USD 72,000.00.",
            "Invoices are payable within 30 days of receipt.",
        ],
        [
            "This agreement is governed by the laws of England and Wales.",
            "Either party may terminate with 60 days written notice.",
            "Non-public information must remain confidential for two years.",
            "Aggregate liability is capped at the total fees paid.",
        ],
    )
    wrapped = commercial[:-1] + [
        "Payment terms: Invoices are payable within 30 days",
        "unless disputed in writing within seven days.",
    ]
    make_pdf("wrapped-agreement.pdf", "Meridian - Wrapped Payment Terms", wrapped, clauses)
    dated = [line.replace("2026-01-15", "01/02/2026") for line in commercial]
    make_pdf("ambiguous-date-agreement.pdf", "Meridian - Ambiguous Date", dated, clauses)
    make_pdf(
        "conflicting-party-agreement.pdf",
        "Meridian - Conflicting Provider",
        commercial,
        clauses + ["Service provider: Alternate Data Works Ltd."],
    )
    cases = [
        case("complete-agreement.pdf", BASE, notes="All fields explicit in labelled English."),
        case(
            "northstar-services.pdf",
            {
                "party_a": "Northstar Analytics Ltd.",
                "party_b": "Acme Digital Studio Inc.",
                "effective_date": "2026-02-01",
                "end_date": None,
                "total_value": "48000.00",
                "currency": "USD",
                "payment_terms": "Within 30 or 60 days of invoice, to be confirmed.",
                "governing_law": None,
                "termination": "Either party may terminate with 30 days written notice.",
                "confidentiality": "Both parties shall protect non-public business information.",
                "liability": "Liability is limited to fees paid under this agreement.",
            },
            {"payment_terms": "uncertain"},
            "Missing fields and ambiguous payment wording.",
        ),
        case(
            "conflicting-agreement.pdf",
            {
                "party_a": "Atlas Systems Ltd.",
                "party_b": "Juniper Design Inc.",
                "effective_date": "2026-06-01",
                "end_date": "2026-01-01",
                "total_value": "-1200.00",
                "currency": "$",
                "payment_terms": "Within 15 days of invoice.",
                "governing_law": "Laws of England and Wales.",
                "termination": "Either party may terminate with 30 days written notice.",
                "confidentiality": "Both parties shall protect confidential information.",
                "liability": "Aggregate liability is capped at fees paid.",
            },
            {
                "end_date": "invalid",
                "total_value": "invalid",
                "currency": "invalid",
                "payment_terms": "uncertain",
            },
            "For conflicting fields, the first explicit candidate is the expected value, with uncertainty preserved.",
        ),
        case(
            "portuguese-agreement.pdf",
            {
                "party_a": "Aurora Dados Ltda.",
                "party_b": "Horizonte Comercio Ltda.",
                "effective_date": "2026-01-15",
                "end_date": "2026-12-31",
                "total_value": "1500.00",
                "currency": "BRL",
                "payment_terms": "Pagamento em ate 15 dias do recebimento.",
                "governing_law": "Leis da Republica Federativa do Brasil.",
                "termination": "Qualquer parte pode rescindir mediante aviso de 30 dias.",
                "confidentiality": "As partes devem proteger informacoes confidenciais.",
                "liability": "Limitada ao total de honorarios pagos.",
            },
            notes="Labelled Portuguese with explicit month names and Brazilian amount separators.",
        ),
        case(
            "prose-agreement.pdf",
            {**BASE, "governing_law": "laws of England and Wales"},
            notes="Narrative phrasing without supported labels. Intentionally exposes baseline limitations.",
        ),
        case(
            "wrapped-agreement.pdf",
            {
                **BASE,
                "payment_terms": "Invoices are payable within 30 days unless disputed in writing within seven days.",
            },
            notes="Full qualification must be preserved. Partial extraction is an error even when flagged uncertain.",
        ),
        case(
            "ambiguous-date-agreement.pdf",
            {**BASE, "effective_date": "01/02/2026"},
            {"effective_date": "uncertain"},
            "Date convention cannot be inferred.",
        ),
        case(
            "conflicting-party-agreement.pdf",
            BASE,
            {"party_a": "uncertain"},
            "Conflicting service-provider candidates on different pages.",
        ),
    ]
    target = ROOT / "app/benchmark/ground-truth.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic-contracts-v1",
                "version": "1.0",
                "description": "Eight authored synthetic documents with manually specified canonical answers. Development benchmark, not an unseen real-world accuracy study.",
                "annotation_policy": "Verbatim clause wording; canonical dates and positive decimal amounts; preserve invalid source values. First candidate for conflicting fields with uncertain status. All eleven fields are annotated.",
                "cases": cases,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("Authored 5 stress PDFs and an 8-document / 88-field benchmark manifest.")
