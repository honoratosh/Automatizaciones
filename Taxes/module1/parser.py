"""
Module 1 - CFDI XML Parser
Extracts the relevant financial fields from CFDI 4.0 XML files.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from datetime import date
import logging

# SAT XML namespaces
NS = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "tfd":  "http://www.sat.gob.mx/TimbreFiscalDigital",
}


@dataclass
class CFDIRecord:
    """Represents a single CFDI invoice with financial and tax information."""
    uuid: str
    fecha: str
    rfc_emisor: str
    nombre_emisor: str
    rfc_receptor: str
    nombre_receptor: str
    subtotal: Decimal
    descuento: Decimal
    total: Decimal
    iva: Decimal = field(default=Decimal("0"))  # IVA trasladado
    isr_retenido: Decimal = field(default=Decimal("0"))  # ISR retenido (if any)
    tipo_comprobante: str = ""  # I=Ingreso, E=Egreso, T=Traslado, N=Nómina
    metodo_pago: str = ""
    moneda: str = "MXN"


def _get_decimal(element, attribute: str, default="0") -> Decimal:
    return Decimal(element.get(attribute, default) or default)


def parse_cfdi_xml(xml_path: Path) -> CFDIRecord | None:
    """
    Parse a single CFDI 4.0 XML file and return a CFDIRecord.
    Returns None if the file cannot be parsed.
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Extract UUID from the Timbre Fiscal Digital
        tfd = root.find(".//tfd:TimbreFiscalDigital", NS)
        uuid = tfd.get("UUID", "") if tfd is not None else ""

        emisor = root.find("cfdi:Emisor", NS)
        receptor = root.find("cfdi:Receptor", NS)

        # Calculate IVA from Impuestos/Traslados
        iva = Decimal("0")
        isr_retenido = Decimal("0")

        impuestos = root.find("cfdi:Impuestos", NS)
        if impuestos is not None:
            for traslado in impuestos.findall(".//cfdi:Traslado", NS):
                if traslado.get("Impuesto") == "002":  # 002 = IVA
                    iva += _get_decimal(traslado, "Importe")

            for retencion in impuestos.findall(".//cfdi:Retencion", NS):
                if retencion.get("Impuesto") == "001":  # 001 = ISR
                    isr_retenido += _get_decimal(retencion, "Importe")

        return CFDIRecord(
            uuid=uuid,
            fecha=root.get("Fecha", ""),
            rfc_emisor=emisor.get("Rfc", "") if emisor is not None else "",
            nombre_emisor=emisor.get("Nombre", "") if emisor is not None else "",
            rfc_receptor=receptor.get("Rfc", "") if receptor is not None else "",
            nombre_receptor=receptor.get("Nombre", "") if receptor is not None else "",
            subtotal=_get_decimal(root, "SubTotal"),
            descuento=_get_decimal(root, "Descuento"),
            total=_get_decimal(root, "Total"),
            iva=iva,
            isr_retenido=isr_retenido,
            tipo_comprobante=root.get("TipoDeComprobante", ""),
            metodo_pago=root.get("MetodoPago", ""),
            moneda=root.get("Moneda", "MXN"),
        )

    except (ET.ParseError, FileNotFoundError, OSError, ValueError, InvalidOperation) as e:
        # Handle common parsing and IO errors without catching all Exceptions
        print(f"⚠ Could not parse {xml_path.name}: {e}")
        return None


def parse_all(xml_paths: list[Path]) -> list[CFDIRecord]:
    """Parse a list of XML file paths. Skips invalid files."""
    records = []
    for path in xml_paths:
        record = parse_cfdi_xml(path)
        if record:
            records.append(record)
    return records


def summarize(records: list[CFDIRecord]) -> dict:
    """
    Produce a financial summary from a list of CFDIRecords.
    Used to feed Module 2 (tax calculator).
    """
    ingresos = sum(
        r.subtotal for r in records if r.tipo_comprobante == "I"
    )
    egresos = sum(
        r.subtotal for r in records if r.tipo_comprobante == "E"
    )
    iva_trasladado = sum(
        r.iva for r in records if r.tipo_comprobante == "I"
    )
    isr_retenido = sum(r.isr_retenido for r in records)

    return {
        "total_ingresos": ingresos,
        "total_egresos": egresos,
        "iva_trasladado": iva_trasladado,
        "isr_retenido": isr_retenido,
        "num_facturas": len(records),
    }


def load_from_local(
    xml_dir: str,
    rfc: str,
    year: int,
    month: int,
) -> dict:
    """
    Scan the local xml_dir and return received/emitted records
    for the given RFC and month, without contacting SAT.
    Used as fallback when SAT returns 5002.
    """
    xml_path = Path(xml_dir)
    if not xml_path.exists():
        raise FileNotFoundError(f"Local XML directory not found: {xml_dir}")

    all_xmls = list(xml_path.glob("*.xml"))
    if not all_xmls:
        raise FileNotFoundError(f"No XML files found in: {xml_dir}")

    received, emitted = [], []

    for xml_file in all_xmls:
        record = parse_cfdi_xml(xml_file)
        if record is None:
            continue

        # Filter by month
        try:
            cfdi_date = date.fromisoformat(record.fecha[:10])
        except ValueError:
            continue

        if cfdi_date.year != year or cfdi_date.month != month:
            continue

        # Filter by RFC and classify direction
        if record.rfc_receptor == rfc and record.tipo_comprobante == "I":
            received.append(record)
        elif record.rfc_emisor == rfc and record.tipo_comprobante == "I":
            emitted.append(record)

    logger = logging.getLogger(__name__)
    logger.info(
        "Local fallback: found %d received "
        "and %d emitted records for %d-%02d",
        len(received), len(emitted), year, month
    )
    return {"received": received, "emitted": emitted}
