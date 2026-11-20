"""Generate reproducible, entirely fictional PDF fixtures. No customer data."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


DESTINATION = Path(__file__).resolve().parents[1] / "app" / "samples"
INK = colors.HexColor("#173c32")
MUTED = colors.HexColor("#657769")


def make_pdf(filename: str, title: str, commercial: list[str], clauses: list[str]):
    DESTINATION.mkdir(parents=True, exist_ok=True)
    doc = canvas.Canvas(str(DESTINATION / filename), pagesize=A4, invariant=True)
    doc.setTitle(title + " - Fictional portfolio sample")
    doc.setAuthor("AI Contract Intelligence / synthetic fixtures")
    for number, (section, rows) in enumerate(
        [("Parties and commercial terms", commercial), ("Conditions and clauses", clauses)], 1
    ):
        doc.setFillColor(INK)
        doc.rect(0, 766, 596, 76, fill=1, stroke=0)
        doc.setFillColor(colors.HexColor("#c5dfb2"))
        doc.setFont("Helvetica-Bold", 10)
        doc.drawString(48, 800, "CONTRACT INTELLIGENCE / SAMPLE LIBRARY")
        doc.setFillColor(MUTED)
        doc.setFont("Helvetica", 9)
        doc.drawString(48, 728, "SYNTHETIC DOCUMENT - FOR SOFTWARE DEMONSTRATION ONLY")
        doc.setFillColor(INK)
        doc.setFont("Helvetica-Bold", 25)
        doc.drawString(48, 682, title)
        doc.setFont("Helvetica", 11)
        doc.setFillColor(MUTED)
        doc.drawString(48, 655, "Professional services agreement")
        doc.setStrokeColor(colors.HexColor("#d8e3d4"))
        doc.line(48, 625, 547, 625)
        doc.setFillColor(INK)
        doc.setFont("Helvetica-Bold", 13)
        doc.drawString(48, 590, section)
        y = 551
        for row in rows:
            doc.setFillColor(INK)
            doc.setFont("Helvetica", 10)
            assert doc.stringWidth(row, "Helvetica", 10) <= 499, (
                f"Sample line exceeds page width: {row}"
            )
            doc.drawString(48, y, row)
            y -= 40
        doc.setFillColor(MUTED)
        doc.setFont("Helvetica", 9)
        doc.drawString(
            48, 164, "This fictional agreement is intentionally simplified for extraction testing."
        )
        doc.drawString(
            48, 149, "It is not a legal template. All parties, values and terms are invented."
        )
        doc.setStrokeColor(colors.HexColor("#d8e3d4"))
        doc.line(48, 105, 547, 105)
        doc.setFont("Helvetica", 8)
        doc.drawString(48, 82, "AI CONTRACT INTELLIGENCE / PORTFOLIO EDITION")
        doc.drawRightString(547, 82, f"Page {number} of 2")
        doc.showPage()
    doc.save()


if __name__ == "__main__":
    make_pdf(
        "northstar-services.pdf",
        "Northstar Services Agreement",
        [
            "Service provider: Northstar Analytics Ltd.",
            "Client: Acme Digital Studio Inc.",
            "Effective date: 2026-02-01",
            "Contract value: 48,000.00",
            "Currency: USD",
            "Payment terms: Within 30 or 60 days of invoice, to be confirmed.",
        ],
        [
            "Termination: Either party may terminate with 30 days written notice.",
            "Confidentiality: Both parties shall protect non-public business information.",
            "Liability: Liability is limited to fees paid under this agreement.",
            "Scope: Monthly analytics and reporting services.",
            "The end date and governing law are intentionally not specified.",
        ],
    )
    make_pdf(
        "complete-agreement.pdf",
        "Meridian Services Agreement",
        [
            "Service provider: Meridian Data Works Ltd.",
            "Client: Harbor Retail Group Inc.",
            "Effective date: 2026-01-15",
            "End date: 2026-12-31",
            "Contract value: 72,000.00",
            "Currency: USD",
            "Payment terms: Invoices are payable within 30 days of receipt.",
        ],
        [
            "Governing law: Laws of England and Wales.",
            "Termination: Either party may terminate with 60 days written notice.",
            "Confidentiality: Non-public information must remain confidential for two years.",
            "Liability: Aggregate liability is capped at the total fees paid.",
            "Scope: Data engineering and monthly operational reporting.",
        ],
    )
    make_pdf(
        "conflicting-agreement.pdf",
        "Atlas Services Agreement",
        [
            "Service provider: Atlas Systems Ltd.",
            "Client: Juniper Design Inc.",
            "Effective date: 2026-06-01",
            "End date: 2026-01-01",
            "Contract value: -1200.00",
            "Currency: $",
            "Payment terms: Within 15 days of invoice.",
        ],
        [
            "Payment terms: Within 60 days of invoice.",
            "Governing law: Laws of England and Wales.",
            "Termination: Either party may terminate with 30 days written notice.",
            "Confidentiality: Both parties shall protect confidential information.",
            "Liability: Aggregate liability is capped at fees paid.",
        ],
    )
    print("Generated 3 fictional, two-page PDF samples.")
