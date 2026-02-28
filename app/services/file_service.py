"""Servicio de gestión de archivos: XML, CDR y PDF.

Lección aprendida de iziFact:
  Centralizar SIEMPRE el guardado de archivos en este módulo.
  NUNCA hacer comprobante.cdr_path = resultado.get('cdr_path')
  ya que ese campo no existe en la respuesta de MiPSE — usar
  guardar_archivos() que decodifica el base64 y escribe el archivo.
"""
import os
import base64
import structlog
from flask import current_app
from app.services import sunat_xml_service

logger = structlog.get_logger()


class FileService:
    """Gestión de archivos de comprobantes electrónicos."""

    def __init__(self, base_path: str, empresa_ruc: str):
        self.base_path = base_path
        self.ruc = empresa_ruc
        os.makedirs(self.base_path, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Guardar archivos desde respuesta MiPSE
    # ─────────────────────────────────────────────────────────────────────────

    def guardar_archivos(self, comprobante, resultado_mipse: dict) -> None:
        """Guarda XML firmado y CDR en disco y actualiza las rutas en el modelo.

        Args:
            comprobante:     Objeto Comprobante de SQLAlchemy.
            resultado_mipse: Dict retornado por mipse_service.procesar_comprobante().

        IMPORTANTE: NO hace commit — el caller debe hacer db.session.commit().
        """
        nombre = resultado_mipse.get('nombre_archivo') or sunat_xml_service.nombre_archivo(comprobante)

        # Guardar XML firmado
        xml_b64 = resultado_mipse.get('xml_firmado_b64') or resultado_mipse.get('xml_firmado')
        if xml_b64:
            try:
                xml_bytes = base64.b64decode(xml_b64)
                xml_path  = os.path.join(self.base_path, f'{nombre}.xml')
                with open(xml_path, 'wb') as f:
                    f.write(xml_bytes)
                comprobante.xml_path = xml_path
                logger.info('file_xml_guardado', path=xml_path)
            except Exception as e:
                logger.error('file_xml_error', nombre=nombre, error=str(e))

        # Guardar CDR (Constancia de Recepción)
        cdr_b64 = resultado_mipse.get('cdr_b64') or resultado_mipse.get('cdr')
        if cdr_b64:
            try:
                cdr_bytes = base64.b64decode(cdr_b64)
                cdr_path  = os.path.join(self.base_path, f'R-{nombre}.xml')
                with open(cdr_path, 'wb') as f:
                    f.write(cdr_bytes)
                comprobante.cdr_path = cdr_path
                logger.info('file_cdr_guardado', path=cdr_path)
            except Exception as e:
                logger.error('file_cdr_error', nombre=nombre, error=str(e))

        # Guardar hash del CPE si viene en la respuesta
        if resultado_mipse.get('hash') and not comprobante.hash_cpe:
            comprobante.hash_cpe = resultado_mipse['hash']

    # ─────────────────────────────────────────────────────────────────────────
    # Guardar PDF
    # ─────────────────────────────────────────────────────────────────────────

    def guardar_pdf(self, comprobante, pdf_bytes: bytes) -> str:
        """Guarda el PDF en disco y actualiza comprobante.pdf_path.

        Returns:
            str: Ruta absoluta del archivo guardado.
        """
        nombre  = sunat_xml_service.nombre_archivo(comprobante)
        pdf_path = os.path.join(self.base_path, f'{nombre}.pdf')
        with open(pdf_path, 'wb') as f:
            f.write(pdf_bytes)
        comprobante.pdf_path = pdf_path
        logger.info('file_pdf_guardado', path=pdf_path)
        return pdf_path

    # ─────────────────────────────────────────────────────────────────────────
    # Regenerar XML desde BD (fallback si el archivo no existe)
    # ─────────────────────────────────────────────────────────────────────────

    def regenerar_xml(self, comprobante) -> bytes:
        """Regenera el XML sin firmar desde los datos en BD.

        Útil como fallback si el archivo XML fue eliminado del disco.
        El XML resultante NO tiene firma digital.

        Returns:
            bytes: XML en ISO-8859-1.
        """
        logger.warning('file_xml_regenerando', comprobante=comprobante.numero_completo)
        return sunat_xml_service.generar_xml(comprobante)

    # ─────────────────────────────────────────────────────────────────────────
    # Importar archivos manualmente
    # ─────────────────────────────────────────────────────────────────────────

    def importar_archivo(self, filename: str, content: bytes) -> dict:
        """Importa un CDR o XML manualmente (desde la página de importación).

        Args:
            filename: Nombre original del archivo subido.
            content:  Bytes del archivo.

        Returns:
            dict: {'path': str, 'tipo': 'xml' | 'cdr' | 'desconocido'}
        """
        nombre_limpio = os.path.basename(filename)
        dest_path = os.path.join(self.base_path, nombre_limpio)
        with open(dest_path, 'wb') as f:
            f.write(content)

        tipo = 'cdr' if nombre_limpio.startswith('R-') else 'xml'
        logger.info('file_importado', path=dest_path, tipo=tipo)
        return {'path': dest_path, 'tipo': tipo}

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers de rutas
    # ─────────────────────────────────────────────────────────────────────────

    def xml_existe(self, comprobante) -> bool:
        return bool(comprobante.xml_path and os.path.isfile(comprobante.xml_path))

    def cdr_existe(self, comprobante) -> bool:
        return bool(comprobante.cdr_path and os.path.isfile(comprobante.cdr_path))

    def pdf_existe(self, comprobante) -> bool:
        return bool(comprobante.pdf_path and os.path.isfile(comprobante.pdf_path))


# ─────────────────────────────────────────────────────────────────────────────
# Instancia de conveniencia (se inicializa dentro del contexto de app)
# ─────────────────────────────────────────────────────────────────────────────

def get_file_service() -> FileService:
    """Retorna una instancia de FileService configurada desde current_app."""
    cfg = current_app.config
    return FileService(
        base_path=cfg.get('COMPROBANTES_PATH', 'comprobantes'),
        empresa_ruc=cfg.get('EMPRESA_RUC', '20605555790'),
    )
