"""Script de mantenimiento: recupera CDRs faltantes desde MiPSE.

Consulta la BD para encontrar comprobantes ENVIADOS o ACEPTADOS sin CDR
en disco y los recupera consultando el estado en MiPSE.

Uso:
    python scripts/heal_cdrs.py [--dry-run] [--estado ENVIADO]

Opciones:
    --dry-run       Solo lista los comprobantes afectados, no modifica nada.
    --estado        Filtrar por estado (ENVIADO, ACEPTADO). Default: ambos.
    --limite N      Máximo de comprobantes a procesar (default: 100).
"""
import argparse
import sys
import os

# Asegurar que el directorio raíz del proyecto esté en el path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import create_app
from app.extensions import db
from app.models.comprobante import Comprobante
from app.services import mipse_service, file_service as file_svc
from app.services.sunat_xml_service import nombre_archivo as nombre_archivo_fn


def main():
    parser = argparse.ArgumentParser(description='Recupera CDRs faltantes desde MiPSE.')
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Solo lista los comprobantes afectados sin modificar nada.',
    )
    parser.add_argument(
        '--estado', choices=['ENVIADO', 'ACEPTADO', 'ambos'], default='ambos',
        help='Filtrar por estado del comprobante (default: ambos).',
    )
    parser.add_argument(
        '--limite', type=int, default=100,
        help='Máximo de comprobantes a procesar (default: 100).',
    )
    args = parser.parse_args()

    app = create_app()

    with app.app_context():
        fs = file_svc.get_file_service()

        # Construir query base
        query = Comprobante.query.filter(
            Comprobante.cdr_path.is_(None) | Comprobante.cdr_path == ''
        )

        if args.estado == 'ENVIADO':
            query = query.filter(Comprobante.estado == 'ENVIADO')
        elif args.estado == 'ACEPTADO':
            query = query.filter(Comprobante.estado == 'ACEPTADO')
        else:
            query = query.filter(Comprobante.estado.in_(['ENVIADO', 'ACEPTADO']))

        comprobantes = query.limit(args.limite).all()

        if not comprobantes:
            print('✅ No se encontraron comprobantes sin CDR en los estados seleccionados.')
            return

        print(f'\n📋 Comprobantes sin CDR encontrados: {len(comprobantes)}')
        print(f'   Modo: {"DRY-RUN (sin cambios)" if args.dry_run else "ACTIVO (guardará CDRs)"}')
        print('-' * 60)

        if args.dry_run:
            for comp in comprobantes:
                nombre = nombre_archivo_fn(comp)
                print(f'  [{comp.estado}] {comp.numero_completo} → archivo: {nombre}')
            print('-' * 60)
            print(f'Total: {len(comprobantes)} comprobante(s) serían procesados.')
            return

        # Obtener token una sola vez para toda la ejecución
        try:
            token = mipse_service.obtener_token()
        except mipse_service.MiPSEError as e:
            print(f'❌ Error obteniendo token MiPSE: {e}')
            sys.exit(1)

        recuperados = 0
        fallidos    = 0

        for comp in comprobantes:
            nombre = nombre_archivo_fn(comp)
            try:
                resultado = mipse_service.consultar_estado(nombre, token)
                cdr_b64 = resultado.get('cdr')

                if not cdr_b64:
                    print(f'  ⚠️  {comp.numero_completo} — MiPSE no devolvió CDR (estado: {resultado.get("estado_sunat", "?")})')
                    fallidos += 1
                    continue

                # Guardar CDR usando file_service
                fs.guardar_archivos(comp, {
                    'nombre_archivo': nombre,
                    'cdr_b64': cdr_b64,
                    'xml_firmado_b64': None,
                })
                db.session.commit()
                print(f'  ✅ {comp.numero_completo} → CDR guardado en {comp.cdr_path}')
                recuperados += 1

            except mipse_service.MiPSEError as e:
                print(f'  ❌ {comp.numero_completo} — Error MiPSE: {e}')
                db.session.rollback()
                fallidos += 1
            except Exception as e:
                print(f'  ❌ {comp.numero_completo} — Error inesperado: {e}')
                db.session.rollback()
                fallidos += 1

        print('-' * 60)
        print(f'Resultado: {recuperados} CDR(s) recuperado(s), {fallidos} fallo(s).')


if __name__ == '__main__':
    main()
