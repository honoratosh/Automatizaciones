"""
Module 1 - Entry Point
Run this to download and parse your CFDIs for a given month.
"""

import logging
import os
from dotenv import load_dotenv
from downloader import build_signer, download_cfdis
from parser import parse_all, summarize, load_from_local

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def run(year: int, month: int) -> dict:
    """Run the full monthly CFDI processing pipeline.

    Args:
        year: The year to process (e.g., 2026).
        month: The month to process (1-12).

    Returns:
        A summary dictionary with totals and counts for the period.
    """
    signer = build_signer(
        cert_path=os.getenv("FIEL_CER", "certs/fiel.cer"),
        key_path=os.getenv("FIEL_KEY", "certs/fiel.key"),
        password_path=os.getenv("FIEL_PASSWORD", "certs/fiel_password.txt"),
    )

    XML_DIR=os.getenv("XML_DIR", "data/xmls")
    
    received_records = []
    emitted_records = []

    try:
        # Step 1: Download XMLs from SAT
        xml_files = download_cfdis(signer, year=year, month=month)

        # Step 2: Parse all XMLs
        received_records = parse_all(xml_files["received"])
        emitted_records = parse_all(xml_files["emitted"])

    except RuntimeError as e:
        if "5002" in str(e):
            # Step 2: Fallback — read from local XML cache
            logging.warning(
                "SAT returned 5002 (lifetime limit reached). "
                "Reading from local XML files instead..."
            )
            local = load_from_local(
                xml_dir=XML_DIR,
                rfc=signer.rfc,
                year=year,
                month=month,
            )
            received_records = local["received"]
            emitted_records  = local["emitted"]
        else:
            raise  # re-raise any other RuntimeError

    # Step 3: Summarize for Module 2
    all_records = received_records + emitted_records
    summary = summarize(all_records)

    if summary["num_facturas"] == 0:
        logging.warning(
            "No CFDIs found — verify the date range and that your "
            "e.firma RFC matches the invoices in data/xmls/."
        )

    print("\n===== CFDI Summary =====")
    print(f"  Period:          {year}-{month:02d}")
    print(f"  Total income:    ${summary['total_ingresos']:,.2f} MXN")
    print(f"  Total expenses:  ${summary['total_egresos']:,.2f} MXN")
    print(f"  IVA collected:   ${summary['iva_trasladado']:,.2f} MXN")
    print(f"  ISR withheld:    ${summary['isr_retenido']:,.2f} MXN")
    print(f"  Invoices found:  {summary['num_facturas']}")
    print("========================\n")

# --- Detail block (TSV — paste directly into Excel) ---
    SEPARATOR = "|"
    headers = [
        #"Type", "Date", "RFC", "Name", "Subtotal", "IVA", "Total"
        "RFC", "Name", "Subtotal", "IVA", "Total","Type"
    ]
    print(SEPARATOR.join(headers))

    for r in sorted(all_records, key=lambda x: x.fecha):
        # From the receiver's perspective:
        #   "I" emitted by someone else → it is our EXPENSE  → show emisor data
        #   "I" emitted by us           → it is our INCOME   → show receptor data
        if r.rfc_emisor == signer.rfc:
            tipo  = "INCOME"
            rfc   = r.rfc_receptor
            name  = r.nombre_receptor
        else:
            tipo  = "EXPENSE"
            rfc   = r.rfc_emisor
            name  = r.nombre_emisor

        row = [
            rfc,
            name,
            str(r.subtotal),
            str(r.iva),
            str(r.total),
            tipo
        ]
        print(SEPARATOR.join(row))

    return summary  # This dict goes directly into Module 2


if __name__ == "__main__":
    # Change year/month to the period you want to process
    run(year=2026, month=3)
