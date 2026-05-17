"""
Module 1 - SAT CFDI Downloader
Downloads received (income) and emitted (expenses) CFDIs
for a given month using the SAT Descarga Masiva web service.
"""

import base64
import time
import zipfile
import logging
from pathlib import Path
from datetime import date

from satcfdi.models import Signer

from satcfdi.pacs.sat import (
    SAT,
    TipoDescargaMasivaTerceros,
    EstadoSolicitud,
    EstadoComprobante,
    CodigoEstadoSolicitud
)

from request_cache import get_request_id, save_request_id

logger = logging.getLogger(__name__)

# SAT's service can take minutes or even hours to process a request.
# These constants control the polling behavior.
POLL_INTERVAL_SECONDS = 30
MAX_POLL_ATTEMPTS = 120  # 60 min max wait

def _request_or_resume(sat_service, signer_rfc, fecha_inicio, fecha_fin, year, month, direction):
    """
    Reuse an existing id_solicitud if available, otherwise make a new request.
    This prevents hitting the 5002 lifetime limit.
    """
    cached_id = get_request_id(signer_rfc, year, month, direction)

    if cached_id:
        logger.info("Resuming existing request [%s]: %s", direction, cached_id)
        return cached_id

    if direction == "received":
        response = sat_service.recover_comprobante_received_request(
            fecha_inicial=fecha_inicio,
            fecha_final=fecha_fin,
            rfc_receptor=signer_rfc,
            tipo_solicitud=TipoDescargaMasivaTerceros.CFDI,
            estado_comprobante=EstadoComprobante.VIGENTE,
        )
    else:
        response = sat_service.recover_comprobante_emitted_request(
            fecha_inicial=fecha_inicio,
            fecha_final=fecha_fin,
            rfc_emisor=signer_rfc,
            tipo_solicitud=TipoDescargaMasivaTerceros.CFDI,
            estado_comprobante=EstadoComprobante.VIGENTE,
        )

    id_solicitud = response["IdSolicitud"]
    save_request_id(signer_rfc, year, month, direction, id_solicitud)
    logger.info("New request [%s]: %s", direction, id_solicitud)
    return id_solicitud


def build_signer(cert_path: str, key_path: str, password_path: str) -> Signer:
    """Load your e.firma (FIEL) certificate into a Signer object."""
    with open(password_path, "r", encoding="utf-8") as f:
        password = f.read().strip()
    return Signer.load(
        certificate=Path(cert_path).read_bytes(),
        key=Path(key_path).read_bytes(),
        password=password,
    )


def _poll_until_ready(sat_service: SAT, id_solicitud: str) -> list[str]:
    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        response = sat_service.recover_comprobante_status(id_solicitud)
        estado = response["EstadoSolicitud"]
        codigo = response.get("CodigoEstadoSolicitud", "")

        logger.info(
            "Attempt %d/%d — Code: %s, Packages: %d",
            attempt,
            MAX_POLL_ATTEMPTS,
            codigo,
            len(response.get('IdsPaquetes', [])),
        )

        if estado == EstadoSolicitud.TERMINADA:
            return response["IdsPaquetes"]

        # 5004 means "no CFDIs found" — valid empty result, not a failure
        if codigo == CodigoEstadoSolicitud.NO_ENCONTRADO:
            logger.warning(
                "SAT returned 5004 (no CFDIs found) for request '%s'. "
                "The period may have no invoices.",
                id_solicitud,
            )
            return []  # ← return empty list instead of raising

        #if estado == EstadoSolicitud.RECHAZADA:
        #    logger.warning(
        #        "SAT returned 5002 (Se agotó las solicitudes de por vida) for request '%s'",
        #        id_solicitud,
        #    )
        #    return []  # ← return empty list instead of raising

        if codigo == CodigoEstadoSolicitud.AGOTADO:
            raise RuntimeError(
                f"5002: Lifetime request limit reached for request '{id_solicitud}'. "
                f"This period cannot be requested again with the same parameters. "
                f"If you still have the ZIPs cached locally, use those instead."
            )

        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError(
        f"SAT did not finish processing '{id_solicitud}' "
        f"after {MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS} seconds."
    )


def _download_and_extract_packages(
    sat_service: SAT,
    package_ids: list[str],
    zip_dir: Path,
    xml_dir: Path,
) -> list[Path]:
    """
    Download each ZIP package from SAT, save it, and extract all XMLs.
    Returns a list of paths to the extracted XML files.
    """
    xml_paths = []

    for pkg_id in package_ids:
        zip_path = zip_dir / f"{pkg_id}.zip"

        # Download only if not already cached locally
        if not zip_path.exists():
            logger.info("Downloading package: %s", pkg_id)
            _response, raw_b64 = sat_service.recover_comprobante_download(
                id_paquete=pkg_id
            )
            zip_path.write_bytes(base64.b64decode(raw_b64))
            logger.info("Saved: %s", zip_path)
        else:
            logger.info("Package already cached: %s", zip_path)

        # Extract XMLs from the ZIP
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                if name.lower().endswith(".xml"):
                    out_path = xml_dir / name
                    if not out_path.exists():
                        out_path.write_bytes(zf.read(name))
                    xml_paths.append(out_path)

    return xml_paths


def download_cfdis(
    signer: Signer,
    year: int,
    month: int,
    zip_dir: str = "data/zips",
    xml_dir: str = "data/xmls",
) -> dict:
    """
    Main function: download all received and emitted CFDIs for a given month.

    Returns a dict with:
        {
            "received": [Path, ...],   # Facturas RECIBIDAS (your expenses)
            "emitted":  [Path, ...],   # Facturas EMITIDAS (your income)
        }
    """
    # Compute the first and last day of the month
    fecha_inicio = date(year, month, 1)
    # Handle month-end correctly (works for any month including December)
    if month == 12:
        fecha_fin = date(year + 1, 1, 1)
    else:
        fecha_fin = date(year, month + 1, 1)

    zip_path = Path(zip_dir)
    xml_path = Path(xml_dir)
    zip_path.mkdir(parents=True, exist_ok=True)
    xml_path.mkdir(parents=True, exist_ok=True)

    sat_service = SAT(signer=signer)
    result = {"received": [], "emitted": []}

    for direction in ("received", "emitted"):
        logger.info("Processing [%s] CFDIs for %s-%02d...", direction, year, month)

        # ← replaces the direct recover_comprobante_*_request() calls
        id_solicitud = _request_or_resume(
            sat_service=sat_service,
            signer_rfc=signer.rfc,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            year=year,
            month=month,
            direction=direction,
        )

        pkg_ids = _poll_until_ready(sat_service, id_solicitud)
        result[direction] = _download_and_extract_packages(
            sat_service, pkg_ids, zip_path, xml_path
        )

    return result
