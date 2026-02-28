"""Tareas programadas con APScheduler.

Tarea principal:
  - enviar_pendientes(): envía comprobantes PENDIENTE/RECHAZADO a SUNAT
    Horario: diario a las 21:00 hora Lima (America/Lima)
    Lock: basado en BD (evita ejecución doble en entornos multi-proceso)
"""
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Inicialización
# ─────────────────────────────────────────────────────────────────────────────

def init_scheduler(app) -> None:
    """Crea y arranca el scheduler. Llamar desde create_app()."""
    global _scheduler

    # En testing no arrancar el scheduler
    if app.config.get('TESTING'):
        return

    if _scheduler is not None and _scheduler.running:
        return

    hora_str = app.config.get('HORARIOS_ENVIO', '21:00')
    try:
        hora, minuto = (int(x) for x in hora_str.split(':'))
    except ValueError:
        hora, minuto = 21, 0

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        func=lambda: _job_enviar_pendientes(app),
        trigger=CronTrigger(hour=hora, minute=minuto, timezone='America/Lima'),
        id='enviar_pendientes',
        replace_existing=True,
        misfire_grace_time=3600,  # Si el servidor estaba caído, ejecutar hasta 1h después
    )
    _scheduler.start()
    logger.info('[SCHEDULER] Iniciado. Tarea enviar_pendientes a las %02d:%02d Lima.', hora, minuto)


def shutdown_scheduler() -> None:
    """Para el scheduler limpiamente (para tests o teardown)."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None


# ─────────────────────────────────────────────────────────────────────────────
# Job principal
# ─────────────────────────────────────────────────────────────────────────────

def _job_enviar_pendientes(app) -> None:
    """Ejecuta el job dentro del contexto de la aplicación Flask."""
    with app.app_context():
        _enviar_pendientes()


def _enviar_pendientes() -> None:
    """Busca comprobantes PENDIENTE y los envía a SUNAT."""
    from app.extensions import db
    from app.models.comprobante import Comprobante
    from app.services import mipse_service, file_service as file_svc

    logger.info('[SCHEDULER] Iniciando envío de pendientes (%s)', _ts())

    pendientes = Comprobante.query.filter(
        Comprobante.estado.in_(('PENDIENTE',))
    ).order_by(Comprobante.fecha_emision).all()

    if not pendientes:
        logger.info('[SCHEDULER] Sin comprobantes pendientes.')
        return

    logger.info('[SCHEDULER] %d comprobante(s) pendiente(s) encontrado(s).', len(pendientes))
    fs = file_svc.get_file_service()
    enviados = errores = 0

    for comp in pendientes:
        try:
            resultado = mipse_service.procesar_comprobante(comp)
            if resultado['success']:
                fs.guardar_archivos(comp, resultado)
                enviados += 1
                logger.info(
                    '[SCHEDULER] Enviado %s → estado=%s',
                    comp.numero_completo, comp.estado,
                )
            else:
                errores += 1
                logger.warning(
                    '[SCHEDULER] Error enviando %s: %s',
                    comp.numero_completo, resultado.get('mensaje_sunat'),
                )
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            errores += 1
            logger.error(
                '[SCHEDULER] Excepción enviando %s: %s',
                comp.numero_completo, exc, exc_info=True,
            )

    logger.info(
        '[SCHEDULER] Fin envío pendientes: %d enviados, %d errores.',
        enviados, errores,
    )


def _ts() -> str:
    return datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
