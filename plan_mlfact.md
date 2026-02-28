# Plan de Implementación — Sistema de Facturación Electrónica para M & L IMPORT EXPORT PERU S.A.C.

## Contexto

Se requiere implementar un sistema de facturación electrónica para la empresa **M & L IMPORT EXPORT PERU S.A.C.** (RUC: 20605555790), una empresa jurídica (RUC 20) que vende los mismos productos que Izistore Peru pero a través de diferentes plataformas. A diferencia del sistema actual (iziFact) que opera bajo el Régimen Único Simplificado (RUS) con RUC 10 donde todos los ítems son inafectos y solo se emiten boletas, este nuevo sistema debe soportar el régimen general con **IGV al 18%** y todos los tipos de comprobante electrónico: **Facturas, Boletas, Notas de Crédito y Notas de Débito**.

El sistema se construirá como un **proyecto completamente independiente** — repositorio, base de datos y configuración separados — pero reutilizará el mismo proveedor PSE (MiPSE, cuenta compartida con empresa agregada) y la misma fuente de productos (WooCommerce). El plan incorpora todas las **lecciones aprendidas** del desarrollo de iziFact para evitar repetir errores y asegurar calidad de producción desde el inicio.

**Nombre del proyecto**: `ArdavFact` (nombre tentativo del sistema)

---

## Fase 0 — Fundación y Arquitectura

**Objetivo**: Establecer la base del proyecto con las mejores prácticas desde el día uno.

### 0.1 Estructura del Proyecto

```
MLFact/
├── app/
│   ├── __init__.py              # create_app() factory, extensiones, config
│   ├── extensions.py            # db, migrate, login_manager, csrf, limiter
│   ├── config.py                # Config, DevelopmentConfig, ProductionConfig
│   │
│   ├── models/
│   │   ├── __init__.py          # Exporta todos los modelos
│   │   ├── usuario.py           # Usuario, Rol, Permiso
│   │   ├── cliente.py           # Cliente
│   │   ├── producto.py          # Producto, Variacion, Categoria, CostoProducto
│   │   ├── comprobante.py       # Comprobante, ComprobanteItem
│   │   └── plantilla.py         # PlantillaComprobante (diseño PDF)
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── sunat_xml_service.py # Generación XML UBL 2.1 (F, B, NC, ND)
│   │   ├── mipse_service.py     # Integración PSE MiPSE (firmar, enviar, consultar)
│   │   ├── pdf_service.py       # Generación PDF con ReportLab
│   │   ├── file_service.py      # Guardar/recuperar archivos (CDR, XML, PDF)
│   │   ├── cliente_service.py   # Búsqueda DNI/RUC (ApisPeru + DB local)
│   │   ├── scheduler_service.py # Tareas programadas (APScheduler)
│   │   ├── woocommerce_service.py # Sync productos y categorías
│   │   └── utils.py             # number_to_words_es, helpers
│   │
│   ├── blueprints/
│   │   ├── __init__.py
│   │   ├── auth/                # Login, registro, logout
│   │   │   ├── __init__.py
│   │   │   ├── routes.py
│   │   │   └── forms.py
│   │   ├── dashboard/           # Dashboard principal
│   │   │   ├── __init__.py
│   │   │   └── routes.py
│   │   ├── ventas/              # POS, CRUD ventas, envío SUNAT
│   │   │   ├── __init__.py
│   │   │   └── routes.py
│   │   ├── comprobantes/        # Descargas PDF/XML/CDR, importación
│   │   │   ├── __init__.py
│   │   │   └── routes.py
│   │   ├── notas/               # NC y ND (creación individual y lote)
│   │   │   ├── __init__.py
│   │   │   └── routes.py
│   │   ├── bulk/                # Carga masiva Excel
│   │   │   ├── __init__.py
│   │   │   └── routes.py
│   │   ├── productos/           # API productos, sync WooCommerce
│   │   │   ├── __init__.py
│   │   │   └── routes.py
│   │   ├── reportes/            # Reportes de ganancias, exportación
│   │   │   ├── __init__.py
│   │   │   └── routes.py
│   │   ├── admin/               # Gestión usuarios, roles, scheduler
│   │   │   ├── __init__.py
│   │   │   └── routes.py
│   │   └── api/                 # Endpoints JSON (clientes, productos)
│   │       ├── __init__.py
│   │       └── routes.py
│   │
│   ├── templates/
│   │   ├── base.html            # Layout maestro (navbar, sidebar, theme, toasts)
│   │   ├── auth/
│   │   │   ├── login.html
│   │   │   └── registro.html
│   │   ├── dashboard/
│   │   │   └── index.html
│   │   ├── ventas/
│   │   │   ├── nueva.html       # POS
│   │   │   ├── lista.html       # Listado con filtros
│   │   │   └── detalle.html     # Vista detallada
│   │   ├── notas/
│   │   │   ├── nueva_nc.html    # Nueva Nota de Crédito
│   │   │   └── nueva_nd.html    # Nueva Nota de Débito
│   │   ├── bulk/
│   │   │   ├── upload.html
│   │   │   └── preview.html
│   │   ├── comprobantes/
│   │   │   └── importar.html    # Importar CDRs/XMLs
│   │   ├── reportes/
│   │   │   └── ganancias.html
│   │   └── admin/
│   │       └── usuarios.html
│   │
│   └── static/
│       ├── css/
│       │   └── theme.css        # Variables CSS, tema claro/oscuro
│       ├── js/
│       │   ├── theme.js         # Toggle tema (prevenir flash)
│       │   ├── toast.js         # Sistema de notificaciones
│       │   └── utils.js         # Helpers compartidos
│       └── img/
│           ├── logo.png
│           └── favicon.ico
│
├── migrations/                  # Flask-Migrate (Alembic) — autogenerado
├── tests/
│   ├── conftest.py              # Fixtures pytest
│   ├── test_models.py
│   ├── test_xml_generation.py   # Tests XML UBL 2.1 contra esquemas
│   ├── test_igv_calculations.py # Tests cálculos IGV
│   ├── test_mipse_integration.py
│   └── test_routes.py
│
├── scripts/
│   ├── create_admin.py          # Crear usuario admin inicial
│   ├── seed_rbac.py             # Seed roles y permisos
│   ├── import_costos.py         # Importar costos de productos
│   └── sync_woo.py              # Sincronización manual WooCommerce
│
├── certificados/                # Certificado digital .pfx (NO en git)
├── .env.example                 # Template de variables de entorno
├── .gitignore
├── Dockerfile
├── docker-compose.yml           # Desarrollo local
├── requirements.txt
├── wsgi.py                      # Punto de entrada Gunicorn
└── README.md
```

### 0.2 Stack Tecnológico

| Componente | Tecnología | Versión | Justificación |
|---|---|---|---|
| Backend | Flask | 3.x | Mismo framework, equipo ya tiene experiencia |
| ORM | SQLAlchemy | 2.0+ | Tipado fuerte, async-ready |
| Base de Datos | PostgreSQL | 15+ | Robusta, JSON nativo, misma que iziFact |
| Migraciones | Flask-Migrate (Alembic) | 4.x | **Lección aprendida**: evitar scripts manuales |
| Autenticación | Flask-Login | 0.6+ | Sesiones, remember-me |
| CSRF | Flask-WTF | 1.2+ | **Lección aprendida**: CSRF desde día 1 |
| Rate Limiting | Flask-Limiter | 3.x | Protección contra abuso |
| PDF | ReportLab | 4.x | Mismo que iziFact, ya probado |
| XML | lxml | 5.x | Generación UBL 2.1, parsing CDR |
| Firma Digital | signxml | 4.x | RSA-SHA1 (requerimiento SUNAT) |
| Certificado | cryptography + pyOpenSSL | Latest | Manejo .pfx |
| HTTP | requests | 2.x | Llamadas a MiPSE y ApisPeru |
| Scheduler | APScheduler | 3.11+ | Envío automático programado |
| Excel | pandas + openpyxl | Latest | Import/export Excel |
| WooCommerce | WooCommerce Python | 3.x | API sync productos |
| Frontend CSS | Bootstrap | 5.3 | Responsive, dark/light mode nativo |
| Frontend Icons | Bootstrap Icons | 1.11+ | Iconografía consistente |
| JS Libs | jQuery 3.7 + Select2 + SweetAlert2 | Latest | Mismas que iziFact |
| WSGI | Gunicorn | 22+ | Producción |
| Contenedor | Docker | Latest | Deploy en Easypanel |
| Logging | Python logging + structlog | Latest | **Lección aprendida**: logging estructurado |

### 0.3 Convenciones y Estándares

| Aspecto | Convención |
|---|---|
| Nombrado de modelos | Singular, PascalCase (`Comprobante`, `ComprobanteItem`) |
| Nombrado de rutas | snake_case (`nueva_venta`, `enviar_sunat`) |
| Nombrado de templates | `blueprint/accion.html` |
| Bloques de template | `{% block title %}`, `{% block content %}`, `{% block extra_css %}`, `{% block modals %}`, `{% block extra_js %}` |
| Respuestas API | `{'success': bool, 'message': str, 'data': {...}}` |
| Flash messages | Categorías: `success`, `warning`, `danger`, `info` |
| Logging | Prefijos: `[VENTA]`, `[SUNAT]`, `[MIPSE]`, `[PDF]`, `[BULK]`, `[SCHEDULER]` |
| Correlativo | `String(10)`, siempre almacenado como string sin ceros a la izquierda internamente, formateado con `zfill(8)` solo para SUNAT |
| Moneda | PEN (Soles), `Numeric(12,2)` para montos |
| Zona horaria | America/Lima (UTC-5) para todas las fechas mostradas |
| Git | Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`) |

---

## Fase 1 — Modelos de Datos y Base de Datos

**Objetivo**: Diseñar e implementar el esquema de base de datos completo con Flask-Migrate.

### 1.1 Modelo: `Usuario`

```python
class Usuario(db.Model, UserMixin):
    __tablename__ = 'usuarios'

    id              = Column(Integer, primary_key=True)
    nombre          = Column(String(100), nullable=False)
    username        = Column(String(50), unique=True, nullable=True)
    email           = Column(String(120), unique=True, nullable=False)
    password_hash   = Column(String(255), nullable=False)
    es_admin        = Column(Boolean, default=False)
    activo          = Column(Boolean, default=True)
    fecha_creacion  = Column(DateTime, default=datetime.utcnow)
    ultimo_login    = Column(DateTime, nullable=True)
    ip_registro     = Column(String(45), nullable=True)  # IPv6 compatible

    # Relaciones
    roles           = relationship('Rol', secondary='usuario_roles', backref='usuarios')
    comprobantes    = relationship('Comprobante', backref='vendedor', foreign_keys='Comprobante.vendedor_id')
```

### 1.2 Modelo: `Rol` y `Permiso`

```python
class Rol(db.Model):
    __tablename__ = 'roles'
    id          = Column(Integer, primary_key=True)
    nombre      = Column(String(50), unique=True, nullable=False)
    descripcion = Column(String(200))
    permisos    = relationship('Permiso', secondary='rol_permisos', backref='roles')

class Permiso(db.Model):
    __tablename__ = 'permisos'
    id     = Column(Integer, primary_key=True)
    nombre = Column(String(100), nullable=False)
    codigo = Column(String(50), unique=True, nullable=False)
    # Códigos: ventas.crear, ventas.ver, ventas.eliminar, nc.crear, nd.crear,
    #          reportes.ver, reportes.exportar, usuarios.gestionar, bulk.upload
```

### 1.3 Modelo: `Cliente`

```python
class Cliente(db.Model):
    __tablename__ = 'clientes'

    id                 = Column(Integer, primary_key=True)
    tipo_documento     = Column(String(3), nullable=False)   # DNI, RUC, CE, PASAPORTE
    numero_documento   = Column(String(15), unique=True, nullable=False)
    # Persona natural
    nombres            = Column(String(200), nullable=True)
    apellido_paterno   = Column(String(100), nullable=True)
    apellido_materno   = Column(String(100), nullable=True)
    # Persona jurídica (RUC 20)
    razon_social       = Column(String(200), nullable=True)
    nombre_comercial   = Column(String(200), nullable=True)
    # Compartidos
    direccion          = Column(String(300), nullable=True)
    email              = Column(String(120), nullable=True)
    telefono           = Column(String(20), nullable=True)
    fecha_creacion     = Column(DateTime, default=datetime.utcnow)

    comprobantes       = relationship('Comprobante', backref='cliente')

    @property
    def nombre_completo(self):
        if self.tipo_documento == 'RUC':
            return self.razon_social or ''
        return f"{self.nombres or ''} {self.apellido_paterno or ''} {self.apellido_materno or ''}".strip()

    @property
    def codigo_tipo_documento_sunat(self):
        """Catálogo 06 SUNAT"""
        return {'DNI': '1', 'CE': '4', 'RUC': '6', 'PASAPORTE': '7'}.get(self.tipo_documento, '0')
```

### 1.4 Modelo: `Comprobante` (reemplaza a `Venta`)

> **Decisión arquitectónica**: Se usa el nombre `Comprobante` en lugar de `Venta` porque el sistema maneja Facturas, Boletas, NCs y NDs — no todas son "ventas". Internamente, la tabla se llama `comprobantes`.

```python
class Comprobante(db.Model):
    __tablename__ = 'comprobantes'

    id                = Column(Integer, primary_key=True)

    # === Identificación del comprobante ===
    tipo_comprobante  = Column(String(20), nullable=False)
    # Valores: FACTURA, BOLETA, NOTA_CREDITO, NOTA_DEBITO
    tipo_documento_sunat = Column(String(2), nullable=False)
    # Valores: '01' (Factura), '03' (Boleta), '07' (NC), '08' (ND)

    serie             = Column(String(10), nullable=False)      # F001, B001, FC01, BC01, FD01, BD01
    correlativo       = Column(String(10), nullable=False)
    numero_completo   = Column(String(20), nullable=False)       # F001-00000001

    # === Relaciones ===
    cliente_id        = Column(Integer, ForeignKey('clientes.id'), nullable=False)
    vendedor_id       = Column(Integer, ForeignKey('usuarios.id'), nullable=True)
    numero_orden      = Column(String(20), nullable=True)        # WooCommerce order #

    # === Montos (CON IGV — precio final) ===
    subtotal          = Column(Numeric(12,2), nullable=False, default=0)     # Suma ítems sin envío
    descuento         = Column(Numeric(12,2), nullable=False, default=0)
    costo_envio       = Column(Numeric(12,2), nullable=False, default=0)     # Siempre en campo, NO como ítem

    # === Desglose tributario ===
    total_operaciones_gravadas   = Column(Numeric(12,2), default=0)  # Base imponible (sin IGV)
    total_operaciones_exoneradas = Column(Numeric(12,2), default=0)
    total_operaciones_inafectas  = Column(Numeric(12,2), default=0)
    total_operaciones_gratuitas  = Column(Numeric(12,2), default=0)
    total_igv                    = Column(Numeric(12,2), default=0)  # Monto IGV
    total                        = Column(Numeric(12,2), nullable=False, default=0)  # Gran total

    # === Estado y fechas ===
    estado            = Column(String(20), default='BORRADOR', nullable=False)
    # Valores: BORRADOR, PENDIENTE, ENVIADO, ACEPTADO, RECHAZADO
    fecha_emision     = Column(DateTime, default=datetime.utcnow, nullable=False)
    fecha_pedido      = Column(DateTime, nullable=True)           # Fecha original WooCommerce
    fecha_envio_sunat = Column(DateTime, nullable=True)
    fecha_vencimiento = Column(DateTime, nullable=True)           # Para facturas

    # === Archivos y respuesta SUNAT ===
    xml_path          = Column(String(500), nullable=True)
    pdf_path          = Column(String(500), nullable=True)
    cdr_path          = Column(String(500), nullable=True)
    hash_cpe          = Column(String(100), nullable=True)
    mensaje_sunat     = Column(Text, nullable=True)
    codigo_sunat      = Column(String(10), nullable=True)
    external_id       = Column(String(100), nullable=True)        # MiPSE UUID

    # === Referencias (NC y ND) ===
    comprobante_referencia_id = Column(Integer, ForeignKey('comprobantes.id'), nullable=True)
    motivo_codigo             = Column(String(5), nullable=True)  # Catálogo 09 (NC) / 10 (ND)
    motivo_descripcion        = Column(String(255), nullable=True)

    # === Relaciones ===
    items              = relationship('ComprobanteItem', backref='comprobante', cascade='all, delete-orphan')
    comprobante_ref    = relationship('Comprobante', remote_side=[id], backref='notas_asociadas')

    # Constraints
    __table_args__ = (
        db.UniqueConstraint('serie', 'correlativo', name='uq_serie_correlativo'),
    )
```

### 1.5 Modelo: `ComprobanteItem`

```python
class ComprobanteItem(db.Model):
    __tablename__ = 'comprobante_items'

    id                = Column(Integer, primary_key=True)
    comprobante_id    = Column(Integer, ForeignKey('comprobantes.id'), nullable=False)

    producto_nombre   = Column(String(300), nullable=False)
    producto_sku      = Column(String(100), nullable=True)
    cantidad          = Column(Numeric(12,2), nullable=False)
    unidad_medida     = Column(String(5), default='NIU')         # NIU=unidad, ZZ=servicio

    # === Precios ===
    precio_unitario_con_igv  = Column(Numeric(12,2), nullable=False)  # Lo que paga el cliente
    precio_unitario_sin_igv  = Column(Numeric(12,2), nullable=False)  # Base para SUNAT
    igv_unitario             = Column(Numeric(12,2), nullable=False, default=0)

    # === Subtotales del ítem ===
    subtotal_sin_igv  = Column(Numeric(12,2), nullable=False)    # cantidad * precio_sin_igv
    igv_total         = Column(Numeric(12,2), nullable=False, default=0)  # cantidad * igv_unitario
    subtotal_con_igv  = Column(Numeric(12,2), nullable=False)    # cantidad * precio_con_igv

    # === Tipo de afectación IGV ===
    tipo_afectacion_igv = Column(String(2), default='10')
    # '10' = Gravado - Operación Onerosa (default para RUC 20)
    # '20' = Exonerado - Operación Onerosa
    # '30' = Inafecto - Operación Onerosa
    # '40' = Exportación

    # === Variación WooCommerce ===
    variacion_id      = Column(Integer, nullable=True)
    atributos_json    = Column(JSON, nullable=True)  # {"Color": "Negro", "Talla": "XL"}
```

### 1.6 Modelos: `Producto`, `Variacion`, `Categoria`, `CostoProducto`

> Idénticos al sistema actual (iziFact). Se reutilizan los mismos modelos ya que los productos son los mismos, sincronizados desde el mismo WooCommerce.

```python
class Categoria(db.Model):
    __tablename__ = 'categorias'
    id        = Column(Integer, primary_key=True)  # WooCommerce ID
    nombre    = Column(String(100))
    slug      = Column(String(100))
    padre_id  = Column(Integer, ForeignKey('categorias.id'), nullable=True)
    count     = Column(Integer, default=0)
    hijos     = relationship('Categoria', backref=db.backref('padre', remote_side=[id]))

class Producto(db.Model):
    __tablename__ = 'productos'
    id                    = Column(Integer, primary_key=True)  # WooCommerce ID
    nombre                = Column(String(255))
    sku                   = Column(String(100), index=True)
    precio                = Column(Numeric(10,2), default=0)       # Precio con IGV
    precio_sin_igv        = Column(Numeric(10,2), default=0)       # Precio base (calculado)
    stock_status          = Column(String(20), default='instock')
    imagen_url            = Column(Text, nullable=True)
    tipo                  = Column(String(20), default='simple')
    fecha_sincronizacion  = Column(DateTime, default=datetime.utcnow)
    variaciones           = relationship('Variacion', backref='producto', cascade='all, delete-orphan')
    categorias            = relationship('Categoria', secondary='producto_categorias', backref='productos')

class Variacion(db.Model):
    __tablename__ = 'variaciones'
    id            = Column(Integer, primary_key=True)  # WooCommerce ID
    producto_id   = Column(Integer, ForeignKey('productos.id'))
    sku           = Column(String(100), index=True)
    precio        = Column(Numeric(10,2), default=0)
    precio_sin_igv = Column(Numeric(10,2), default=0)
    stock_status  = Column(String(20), default='instock')
    imagen_url    = Column(Text, nullable=True)
    atributos     = Column(JSON, nullable=False)

class CostoProducto(db.Model):
    __tablename__ = 'costos_productos'
    id        = Column(Integer, primary_key=True)
    sku       = Column(String(100), index=True)
    desc      = Column(String(255))
    colorcode = Column(String(100))
    sizecode  = Column(String(100))
    costo     = Column(Numeric(10,2), default=0)
```

### 1.7 Modelo: `PlantillaComprobante`

```python
class PlantillaComprobante(db.Model):
    __tablename__ = 'plantillas_comprobante'
    id                 = Column(Integer, primary_key=True)
    nombre             = Column(String(100))
    tipo               = Column(String(20))  # 'A4', 'TICKET_80MM'
    es_activo          = Column(Boolean, default=False)
    html_content       = Column(Text)
    css_content        = Column(Text)
    config_json        = Column(JSON, default={})
    fecha_creacion     = Column(DateTime, default=datetime.utcnow)
    fecha_modificacion = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### 1.8 Lógica de Series y Correlativos

```
Tipo Comprobante    | Serie Default | tipo_documento_sunat | Uso
--------------------|---------------|----------------------|---------------------------
FACTURA             | F001          | 01                   | Ventas a clientes con RUC
BOLETA              | B001          | 03                   | Ventas a clientes con DNI/CE
NOTA_CREDITO (F)    | FC01          | 07                   | NC referenciando Factura
NOTA_CREDITO (B)    | BC01          | 07                   | NC referenciando Boleta
NOTA_DEBITO (F)     | FD01          | 08                   | ND referenciando Factura
NOTA_DEBITO (B)     | BD01          | 08                   | ND referenciando Boleta
```

**Regla de asignación automática de serie**:
- Si el cliente tiene `tipo_documento == 'RUC'` → **Factura (F001)**
- Si el cliente tiene `tipo_documento == 'DNI'` o `'CE'` o `'PASAPORTE'` → **Boleta (B001)**
- NC/ND hereda del comprobante de referencia: si ref es F001 → FC01/FD01, si ref es B001 → BC01/BD01

### 1.9 Cálculos IGV

```python
IGV_RATE = 0.18  # 18%

def calcular_igv_item(precio_con_igv: Decimal, cantidad: Decimal, tipo_afectacion: str = '10'):
    """
    Calcula el desglose de IGV para un ítem.
    Los precios de WooCommerce INCLUYEN IGV.
    """
    if tipo_afectacion == '10':  # Gravado
        precio_sin_igv = (precio_con_igv / Decimal('1.18')).quantize(Decimal('0.01'))
        igv_unitario = (precio_con_igv - precio_sin_igv).quantize(Decimal('0.01'))
    elif tipo_afectacion == '20':  # Exonerado
        precio_sin_igv = precio_con_igv
        igv_unitario = Decimal('0.00')
    elif tipo_afectacion == '30':  # Inafecto
        precio_sin_igv = precio_con_igv
        igv_unitario = Decimal('0.00')
    else:
        precio_sin_igv = precio_con_igv
        igv_unitario = Decimal('0.00')

    subtotal_sin_igv = (precio_sin_igv * cantidad).quantize(Decimal('0.01'))
    igv_total = (igv_unitario * cantidad).quantize(Decimal('0.01'))
    subtotal_con_igv = (subtotal_sin_igv + igv_total).quantize(Decimal('0.01'))

    return {
        'precio_sin_igv': precio_sin_igv,
        'igv_unitario': igv_unitario,
        'subtotal_sin_igv': subtotal_sin_igv,
        'igv_total': igv_total,
        'subtotal_con_igv': subtotal_con_igv,
    }

def calcular_totales_comprobante(items: list[ComprobanteItem], costo_envio: Decimal = Decimal('0')):
    """
    Calcula los totales tributarios del comprobante.
    """
    total_gravadas = sum(i.subtotal_sin_igv for i in items if i.tipo_afectacion_igv == '10')
    total_exoneradas = sum(i.subtotal_sin_igv for i in items if i.tipo_afectacion_igv == '20')
    total_inafectas = sum(i.subtotal_sin_igv for i in items if i.tipo_afectacion_igv == '30')
    total_igv = sum(i.igv_total for i in items if i.tipo_afectacion_igv == '10')

    # El envío también está gravado
    if costo_envio > 0:
        envio_sin_igv = (costo_envio / Decimal('1.18')).quantize(Decimal('0.01'))
        igv_envio = (costo_envio - envio_sin_igv).quantize(Decimal('0.01'))
        total_gravadas += envio_sin_igv
        total_igv += igv_envio

    total = total_gravadas + total_exoneradas + total_inafectas + total_igv

    return {
        'total_gravadas': total_gravadas,
        'total_exoneradas': total_exoneradas,
        'total_inafectas': total_inafectas,
        'total_igv': total_igv,
        'total': total,
    }
```

### 1.10 Decisión sobre Envío (Lección Aprendida)

> **Lección de iziFact**: El envío se manejaba de dos formas — como `VentaItem(sku='ENVIO')` en ventas nuevas y como `venta.costo_envio` en históricas. Esto generó duplicidad y bugs constantes con el flag `tiene_item_envio`.

**Decisión para MLFact**: El envío se maneja **SIEMPRE como campo** `comprobante.costo_envio`, **NUNCA como ítem**. Se incluye en el XML como parte de las operaciones gravadas pero no aparece como línea de ítem separada. Se muestra en el PDF como línea independiente de los productos.

### 1.11 Migraciones

```bash
# Inicializar Flask-Migrate (una sola vez)
flask db init

# Crear migración tras cambiar modelos
flask db migrate -m "descripción del cambio"

# Aplicar migración
flask db upgrade

# Revertir migración
flask db downgrade
```

**Archivos a crear en esta fase**:
- `app/models/*.py` — Todos los modelos
- `app/extensions.py` — SQLAlchemy, Migrate, LoginManager, CSRFProtect, Limiter
- `app/config.py` — Configuraciones por entorno
- `app/__init__.py` — Factory `create_app()`
- `migrations/` — Autogenerado por Flask-Migrate
- `scripts/create_admin.py`, `scripts/seed_rbac.py`
- `.env.example`

---

## Fase 2 — Autenticación, Autorización y Layout Base

**Objetivo**: Implementar el sistema de login, RBAC y el template base con diseño profesional.

### 2.1 Autenticación

- Login por email o username + contraseña
- Registro con whitelist de correos autorizados
- Remember-me con cookie segura
- Auditoría: `ultimo_login`, `ip_registro`
- Protección: `@login_required` en todas las rutas protegidas
- CSRF token en todos los formularios y peticiones AJAX
- Rate limiting: 5 intentos/minuto en login, 3 registros/hora

### 2.2 RBAC (Roles y Permisos)

```
Roles predefinidos:
├── Administrador → todos los permisos
├── Vendedor → ventas.crear, ventas.ver, nc.crear, reportes.ver
├── Almacén → ventas.ver, bulk.upload
└── Consulta → ventas.ver, reportes.ver
```

### 2.3 Template Base (`base.html`)

**Diseño**: Moderno, sobrio, elegante. Paleta profesional con azules corporativos.

**Estructura**:
```
┌──────────────────────────────────────────────────────┐
│  NAVBAR (fixed-top, blur backdrop)                   │
│  Logo MLFact  │  RUC: 20605555790  │  User ▼ Logout  │
├──────┬───────────────────────────────────────────────┤
│ SIDE │  CONTENT AREA                                 │
│ BAR  │                                               │
│      │  {% block content %}                          │
│ Nav  │                                               │
│ Links│                                               │
│      │                                               │
│      │                                               │
├──────┴───────────────────────────────────────────────┤
│  Toast Container (top-right, z-9999)                 │
└──────────────────────────────────────────────────────┘
```

**Sidebar Links**:
- Dashboard
- Nueva Venta (POS)
- Comprobantes (lista)
- Carga Masiva
- Diseño de Comprobante
- Reportes → Ganancias
- Admin → Gestión de Equipo (permiso: `usuarios.gestionar`)

**Tema claro/oscuro**: Mismo patrón que iziFact, con variables CSS y localStorage, script anti-flash en `<head>`.

**Toast System**: Extracto a `static/js/toast.js` (no inline) con las mismas funciones: `showToast(title, message, type)`.

**Librerías incluidas**: Bootstrap 5.3, Bootstrap Icons 1.11, jQuery 3.7, Select2 4.1, SweetAlert2 11.

**Archivos a crear en esta fase**:
- `app/blueprints/auth/routes.py` — Login, registro, logout
- `app/templates/base.html` — Layout maestro completo
- `app/templates/auth/login.html` — Página de login (split-screen, elegante)
- `app/static/css/theme.css` — Variables CSS para tema claro/oscuro
- `app/static/js/theme.js` — Toggle tema
- `app/static/js/toast.js` — Sistema de notificaciones toast
- `app/static/js/utils.js` — Helpers JS compartidos

---

## Fase 3 — Dashboard y Sistema POS

**Objetivo**: Implementar el dashboard con indicadores y la interfaz POS para crear comprobantes.

### 3.1 Dashboard

**Indicadores**:
- **Facturas Emitidas** (mes actual): Count de FACTURA con estado no BORRADOR/RECHAZADO
- **Boletas Emitidas** (mes actual): Count de BOLETA con estado no BORRADOR/RECHAZADO
- **Notas de Crédito**: Count de NC emitidas en el mes
- **Pendientes de Envío**: Count de estado='PENDIENTE'
- **Rechazadas**: Count de estado='RECHAZADO' (resaltado en rojo si > 0)
- **Facturación del Mes**: Total facturado (base imponible + IGV), con gráfico de barras semanal
- **IGV del Mes**: Total IGV cobrado (útil para declaraciones)

**Últimos Comprobantes**: Tabla con los 10 más recientes (tipo badge, número, cliente, total, estado, fecha, acciones).

> **Diferencia con iziFact**: No hay semáforo RUS (no aplica para régimen general). Se reemplaza por indicador de IGV mensual acumulado.

### 3.2 POS (Point of Sale)

**Layout**: Idéntico al de iziFact — catálogo de productos a la izquierda, carrito a la derecha.

**Flujo**:
1. Vendedor busca/selecciona cliente → sistema determina automáticamente: RUC → Factura, DNI/CE → Boleta
2. Badge visible indica tipo de comprobante que se emitirá: "Se emitirá: FACTURA F001" o "Se emitirá: BOLETA B001"
3. Busca productos por nombre/SKU/categoría
4. Agrega ítems al carrito con cantidad
5. Sistema muestra desglose en tiempo real:
   - Subtotal (base imponible sin IGV)
   - IGV 18%
   - Envío (si aplica)
   - **TOTAL**
6. Click "Emitir Comprobante" → SweetAlert confirmación → Envío inmediato a SUNAT

**Cálculo IGV en el frontend** (JavaScript):
```javascript
function calcularTotales() {
    let totalSinIGV = 0;
    let totalIGV = 0;

    items.forEach(item => {
        const precioSinIGV = item.precioConIGV / 1.18;
        const igv = item.precioConIGV - precioSinIGV;
        totalSinIGV += precioSinIGV * item.cantidad;
        totalIGV += igv * item.cantidad;
    });

    // Envío gravado
    if (costoEnvio > 0) {
        const envioSinIGV = costoEnvio / 1.18;
        totalSinIGV += envioSinIGV;
        totalIGV += costoEnvio - envioSinIGV;
    }

    const total = totalSinIGV + totalIGV;

    document.getElementById('subtotal').textContent = formatMoney(totalSinIGV);
    document.getElementById('igv').textContent = formatMoney(totalIGV);
    document.getElementById('total').textContent = formatMoney(total);
}
```

**Validaciones**:
- Cliente obligatorio antes de agregar ítems
- Al menos 1 ítem en el carrito
- Cantidades > 0
- Confirmación SweetAlert antes de emitir
- Loading state con spinner durante envío a SUNAT
- Resultado: toast de éxito o modal de error con detalle

**Archivos a crear en esta fase**:
- `app/blueprints/dashboard/routes.py`
- `app/blueprints/ventas/routes.py` — `nueva_venta` (GET/POST)
- `app/blueprints/api/routes.py` — Endpoints de clientes y productos
- `app/services/cliente_service.py` — Búsqueda DNI/RUC
- `app/templates/dashboard/index.html`
- `app/templates/ventas/nueva.html` — POS

---

## Fase 4 — Generación XML UBL 2.1 y Envío a SUNAT vía MiPSE

**Objetivo**: Implementar la generación de XML para todos los tipos de comprobante con IGV y la integración con MiPSE.

### 4.1 XML UBL 2.1 — Estructura para Factura/Boleta con IGV

**Diferencias clave respecto a iziFact (que es inafecto)**:

| Aspecto | iziFact (RUS) | MLFact (Régimen General) |
|---|---|---|
| TaxCode | 9998 (Inafecto) | 1000 (IGV) |
| TaxTypeCode | FRE | VAT |
| TaxExemptionReasonCode | 30 (Inafecto) | 10 (Gravado oneroso) |
| TaxableAmount | = precio total | = precio sin IGV |
| TaxAmount | 0.00 | = 18% del TaxableAmount |
| LineExtensionAmount | = precio total | = suma precios sin IGV |
| TaxInclusiveAmount | = precio total | = LineExtension + TaxAmount |
| PayableAmount | = total | = TaxInclusiveAmount |
| Percent en TaxSubtotal | 0.00 | 18.00 |
| InvoiceTypeCode | 03 (solo Boleta) | 01 (Factura) o 03 (Boleta) |

**Estructura XML Factura (tipo 01)**:
```xml
<?xml version="1.0" encoding="ISO-8859-1"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="..." xmlns:cbc="..." xmlns:ext="...">

  <ext:UBLExtensions>
    <ext:UBLExtension>
      <ext:ExtensionContent/>  <!-- Firma digital aquí -->
    </ext:UBLExtension>
  </ext:UBLExtensions>

  <cbc:UBLVersionID>2.1</cbc:UBLVersionID>
  <cbc:CustomizationID>2.0</cbc:CustomizationID>
  <cbc:ID>F001-00000001</cbc:ID>
  <cbc:IssueDate>2026-02-25</cbc:IssueDate>
  <cbc:IssueTime>14:30:00</cbc:IssueTime>
  <cbc:DueDate>2026-03-25</cbc:DueDate>  <!-- Solo facturas -->
  <cbc:InvoiceTypeCode listID="0101">01</cbc:InvoiceTypeCode>  <!-- 01=Factura -->
  <cbc:DocumentCurrencyCode>PEN</cbc:DocumentCurrencyCode>

  <!-- Firma -->
  <cac:Signature>...</cac:Signature>

  <!-- Emisor (Empresa) -->
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyIdentification>
        <cbc:ID schemeID="6">20605555790</cbc:ID>  <!-- RUC 20 -->
      </cac:PartyIdentification>
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>M & L IMPORT EXPORT PERU S.A.C.</cbc:RegistrationName>
        <cac:RegistrationAddress>
          <cbc:ID>[UBIGEO]</cbc:ID>
          <cbc:AddressTypeCode listAgencyName="PE:SUNAT">0000</cbc:AddressTypeCode>
          <cbc:StreetName>[DIRECCIÓN]</cbc:StreetName>
          ...
        </cac:RegistrationAddress>
      </cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingSupplierParty>

  <!-- Receptor (Cliente) -->
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyIdentification>
        <cbc:ID schemeID="6">[RUC_CLIENTE]</cbc:ID>  <!-- schemeID según catálogo 06 -->
      </cac:PartyIdentification>
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>[RAZÓN SOCIAL]</cbc:RegistrationName>
      </cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingCustomerParty>

  <!-- Totales Tributarios -->
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="PEN">[TOTAL_IGV]</cbc:TaxAmount>
    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="PEN">[TOTAL_GRAVADAS]</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="PEN">[TOTAL_IGV]</cbc:TaxAmount>
      <cac:TaxCategory>
        <cbc:Percent>18.00</cbc:Percent>
        <cac:TaxScheme>
          <cbc:ID>1000</cbc:ID>                    <!-- IGV -->
          <cbc:Name>IGV</cbc:Name>
          <cbc:TaxTypeCode>VAT</cbc:TaxTypeCode>
        </cac:TaxScheme>
      </cac:TaxCategory>
    </cac:TaxSubtotal>
  </cac:TaxTotal>

  <!-- Totales Monetarios -->
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="PEN">[TOTAL_GRAVADAS]</cbc:LineExtensionAmount>
    <cbc:TaxInclusiveAmount currencyID="PEN">[TOTAL]</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="PEN">[TOTAL]</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>

  <!-- Líneas -->
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="NIU">2.00</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="PEN">[SUBTOTAL_SIN_IGV]</cbc:LineExtensionAmount>
    <cac:PricingReference>
      <cac:AlternativeConditionPrice>
        <cbc:PriceAmount currencyID="PEN">[PRECIO_CON_IGV]</cbc:PriceAmount>
        <cbc:PriceTypeCode>01</cbc:PriceTypeCode>
      </cac:AlternativeConditionPrice>
    </cac:PricingReference>
    <cac:TaxTotal>
      <cbc:TaxAmount currencyID="PEN">[IGV_ITEM]</cbc:TaxAmount>
      <cac:TaxSubtotal>
        <cbc:TaxableAmount currencyID="PEN">[SUBTOTAL_SIN_IGV]</cbc:TaxableAmount>
        <cbc:TaxAmount currencyID="PEN">[IGV_ITEM]</cbc:TaxAmount>
        <cac:TaxCategory>
          <cbc:Percent>18.00</cbc:Percent>
          <cbc:TaxExemptionReasonCode>10</cbc:TaxExemptionReasonCode>
          <cac:TaxScheme>
            <cbc:ID>1000</cbc:ID>
            <cbc:Name>IGV</cbc:Name>
            <cbc:TaxTypeCode>VAT</cbc:TaxTypeCode>
          </cac:TaxScheme>
        </cac:TaxCategory>
      </cac:TaxSubtotal>
    </cac:TaxTotal>
    <cac:Item>
      <cbc:Description>[PRODUCTO]</cbc:Description>
      <cac:SellersItemIdentification>
        <cbc:ID>[SKU]</cbc:ID>
      </cac:SellersItemIdentification>
    </cac:Item>
    <cac:Price>
      <cbc:PriceAmount currencyID="PEN">[PRECIO_SIN_IGV]</cbc:PriceAmount>
    </cac:Price>
  </cac:InvoiceLine>
</Invoice>
```

### 4.2 XML Nota de Crédito (tipo 07) — Con IGV

Misma estructura tributaria que Factura/Boleta pero con:
- Elemento raíz: `CreditNote`
- `CreditNoteLine` en lugar de `InvoiceLine`
- `CreditedQuantity` en lugar de `InvoicedQuantity`
- `BillingReference` → referencia al comprobante original
- `DiscrepancyResponse` → motivo (Catálogo 09)

### 4.3 XML Nota de Débito (tipo 08) — Con IGV

Misma estructura pero con:
- Elemento raíz: `DebitNote`
- `DebitNoteLine` en lugar de `InvoiceLine`
- `DebitedQuantity` en lugar de `InvoicedQuantity`
- `BillingReference` → referencia al comprobante original
- `DiscrepancyResponse` → motivo (Catálogo 10)

**Motivos Nota de Débito (Catálogo 10 SUNAT)**:
```python
MOTIVOS_ND = {
    '01': 'Intereses por mora',
    '02': 'Aumento en el valor',
    '03': 'Penalidades / otros conceptos',
}
```

**Motivos Nota de Crédito (Catálogo 09 SUNAT)** — mismos que iziFact:
```python
MOTIVOS_NC = {
    '01': 'Anulación de la operación',
    '02': 'Anulación por error en el RUC',
    '03': 'Corrección por error en la descripción',
    '04': 'Descuento global',
    '05': 'Descuento por ítem',
    '06': 'Devolución total',
    '07': 'Devolución por ítem',
    '08': 'Bonificación',
    '09': 'Disminución en el valor',
}
```

### 4.4 Integración MiPSE

> Misma integración que iziFact, solo cambian las credenciales (usuario/password de MiPSE para la nueva empresa).

**Flujo**:
1. `obtener_token_acceso()` → POST `/pro/{system}/auth/cpe/token`
2. `firmar_xml(nombre, xml_base64)` → POST `/pro/{system}/cpe/generar`
3. `enviar_comprobante(nombre, xml_firmado)` → POST `/pro/{system}/cpe/enviar`
4. `consultar_estado(nombre)` → GET `/pro/{system}/cpe/consultar/{nombre}`

**Manejo de duplicados**: Misma lógica — si `enviar` falla con "ya existe" / "registrado", intentar `consultar_estado` para recuperar CDR.

### 4.5 `file_service.py` (Lección Aprendida)

> **Lección de iziFact**: `guardar_archivos_mipse()` estaba en `app.py` y `enviar_lote` usaba `resultado.get('cdr_path')` (siempre None) en lugar de llamar a esta función. Se crea un servicio dedicado.

```python
# app/services/file_service.py
class FileService:
    def __init__(self, comprobantes_path: str, empresa_ruc: str):
        self.base_path = comprobantes_path
        self.ruc = empresa_ruc
        os.makedirs(self.base_path, exist_ok=True)

    def guardar_archivos(self, comprobante, resultado_mipse: dict):
        """Guarda XML firmado y CDR desde la respuesta de MiPSE.
        SIEMPRE usar esta función después de enviar a SUNAT.
        NUNCA hacer comprobante.cdr_path = resultado.get('cdr_path').
        """
        nombre = resultado_mipse.get('nombre_archivo', '')

        if resultado_mipse.get('xml_firmado'):
            xml_bytes = base64.b64decode(resultado_mipse['xml_firmado'])
            xml_path = os.path.join(self.base_path, f"{nombre}.xml")
            with open(xml_path, 'wb') as f:
                f.write(xml_bytes)
            comprobante.xml_path = xml_path

        if resultado_mipse.get('cdr'):
            cdr_bytes = base64.b64decode(resultado_mipse['cdr'])
            cdr_path = os.path.join(self.base_path, f"R-{nombre}.xml")
            with open(cdr_path, 'wb') as f:
                f.write(cdr_bytes)
            comprobante.cdr_path = cdr_path

    def regenerar_xml(self, comprobante) -> bytes:
        """Regenera XML desde los datos en BD (fallback si archivo no existe)."""
        ...

    def importar_archivo(self, filename: str, content: bytes) -> dict:
        """Importa CDR o XML manualmente (página de importación)."""
        ...
```

**Archivos a crear en esta fase**:
- `app/services/sunat_xml_service.py` — Generación XML para F, B, NC, ND con IGV
- `app/services/mipse_service.py` — Integración MiPSE (basado en iziFact)
- `app/services/file_service.py` — Gestión de archivos
- Tests: `tests/test_xml_generation.py`, `tests/test_igv_calculations.py`

---

## Fase 5 — Listado de Comprobantes, Detalle, Descargas y Notas

**Objetivo**: Implementar la vista de lista con filtros, detalle de comprobante, descargas (PDF/XML/CDR) y emisión de NC/ND.

### 5.1 Lista de Comprobantes

**Filtros**:
- Por tipo de comprobante: Todos, Facturas, Boletas, NC, ND
- Por DNI/RUC
- Por nombre/razón social
- Por número de comprobante
- Por número de orden
- Por rango de fechas
- Por estado: Todos, Pendiente, Enviado, Aceptado, Rechazado

**Columnas**: Checkbox, N° Orden, Tipo (badge), Comprobante, Cliente, Documento, Total, IGV, Estado, Fecha, Acciones.

**Badges por tipo**:
- FACTURA: Azul primary
- BOLETA: Gris secondary
- NC: Naranja warning
- ND: Rojo-claro info

**Acciones masivas**: Enviar a SUNAT, Emitir NC, Descargar ZIP (PDF/XML/CDR), Eliminar.

**Paginación**: 25 por página con links inteligentes.

**Ordenamiento**: Por todas las columnas, toggle asc/desc.

### 5.2 Detalle de Comprobante

Similar a iziFact pero con desglose IGV:
- Info general + estado + fechas
- Info cliente
- Tabla de ítems con columnas: Producto, Cant., P.Unit (sin IGV), IGV, Subtotal
- Resumen fiscal:
  - Op. Gravadas: S/ XXX.XX
  - Op. Exoneradas: S/ 0.00
  - Op. Inafectas: S/ 0.00
  - IGV 18%: S/ XXX.XX
  - Envío: S/ XXX.XX
  - **TOTAL: S/ XXX.XX**
- Acciones: PDF, XML, CDR, Emitir NC, Emitir ND, Enviar SUNAT, Volver

### 5.3 PDF con Desglose IGV

**Sección de totales en el PDF** (diferencia principal con iziFact):
```
OP. GRAVADAS        S/    847.46
OP. EXONERADAS      S/      0.00
OP. INAFECTAS       S/      0.00
I.G.V. 18%          S/    152.54
ENVÍO (GRAVADO)     S/     15.00
────────────────────────────────
IMPORTE TOTAL       S/  1,015.00
```

**QR Code** (formato pipe-separated SUNAT):
```
{RUC}|{TIPO_DOC}|{SERIE}|{CORRELATIVO}|{IGV}|{TOTAL}|{FECHA}|{TIPO_DOC_CLIENTE}|{NUM_DOC_CLIENTE}|{HASH}|
```

**Título del PDF** según tipo:
- `FACTURA ELECTRÓNICA` (F001)
- `BOLETA DE VENTA ELECTRÓNICA` (B001)
- `NOTA DE CRÉDITO ELECTRÓNICA` (FC01/BC01)
- `NOTA DE DÉBITO ELECTRÓNICA` (FD01/BD01)

### 5.4 Nota de Crédito

- Seleccionar comprobante de referencia (solo ENVIADO/ACEPTADO sin NC previa)
- Mostrar ítems del original
- Seleccionar motivo (Catálogo 09)
- Emisión inmediata a SUNAT
- NC Lote: Modal con progreso (idéntico a iziFact)

### 5.5 Nota de Débito

- Seleccionar comprobante de referencia
- Seleccionar motivo (Catálogo 10)
- Permitir ajustar monto (a diferencia de NC que es por total)
- Campos: monto adicional, descripción detallada
- Emisión inmediata a SUNAT

### 5.6 Descargas y Recuperación

- **PDF**: Generar con ReportLab y descargar
- **XML**: Descargar archivo guardado o regenerar desde BD (lección aprendida)
- **CDR**: Descargar archivo guardado o intentar recuperar de MiPSE

**Archivos a crear en esta fase**:
- `app/blueprints/ventas/routes.py` — Lista, detalle
- `app/blueprints/comprobantes/routes.py` — PDF, XML, CDR, importar
- `app/blueprints/notas/routes.py` — NC individual, NC lote, ND
- `app/services/pdf_service.py` — PDF con desglose IGV
- `app/templates/ventas/lista.html`, `detalle.html`
- `app/templates/notas/nueva_nc.html`, `nueva_nd.html`
- `app/templates/comprobantes/importar.html`

---

## Fase 6 — Carga Masiva, Sincronización WooCommerce y Scheduler

**Objetivo**: Replicar la funcionalidad de carga masiva desde Excel, sync de productos desde WooCommerce y el scheduler de envío automático.

### 6.1 Carga Masiva (Bulk Upload)

**Flujo idéntico a iziFact**:
1. Subir archivo Excel (.xlsx) con pedidos de WooCommerce
2. Analizar: parsear SKUs, match productos, validar clientes, detectar duplicados
3. Preview: tabla con status (OK/WARNING/ERROR) por orden
4. Procesar: crear comprobantes + enviar a SUNAT con barra de progreso

**Diferencias con iziFact**:
- Determinar automáticamente Factura vs Boleta según tipo documento del cliente
- Calcular IGV por cada ítem
- Sin semáforo RUS (no aplica)
- Mostrar desglose IGV en preview

**Columnas Excel** (mismas que iziFact — mismo WooCommerce):
```
B(1)=SKU, D(3)=Fecha, E(4)=N° Orden, J(9)=Nombre, L(11)=DNI/RUC,
AJ(35)=Precio, AK(36)=Descripción, AL(37)=Costo Envío
```

### 6.2 Sincronización WooCommerce

> Mismo WooCommerce, mismos productos. El servicio `woocommerce_service.py` será idéntico pero conectado a la BD de MLFact.

**Endpoints**:
- `GET /api/sync-woo` — Sincronización manual de productos y categorías
- `GET /api/get-categories` — Categorías en árbol
- `GET /api/get-products-by-category/<id>` — Productos por categoría
- `GET /api/search-products?q=` — Búsqueda texto libre

**Diferencia**: Al sincronizar precios, calcular y almacenar `precio_sin_igv` = precio / 1.18.

### 6.3 Importación de Costos

> Mismo sistema que iziFact — CSV/Excel con SKU + costo.

### 6.4 Scheduler

**Tareas programadas**:
- `enviar_pendientes()` — Enviar comprobantes PENDIENTE a SUNAT (diario, 21:00 Lima)
- Usa `file_service.guardar_archivos()` (lección aprendida: nunca `resultado.get('cdr_path')`)
- Lock: database-based (no file lock como iziFact, más robusto en Docker)

**Archivos a crear en esta fase**:
- `app/blueprints/bulk/routes.py` — Upload, preview, process
- `app/blueprints/productos/routes.py` — Sync WooCommerce
- `app/services/woocommerce_service.py`
- `app/services/scheduler_service.py`
- `app/templates/bulk/upload.html`, `preview.html`
- `scripts/import_costos.py`, `scripts/sync_woo.py`

---

## Fase 7 — Reportes, Administración y Diseño de Comprobante

**Objetivo**: Implementar reportes de ganancias con desglose IGV, gestión de usuarios y editor de plantilla.

### 7.1 Reporte de Ganancias

**Cards resumen** (5 columnas):
- Total Ingresos (con IGV)
- Total IGV Cobrado
- Costo Productos
- Gasto Envío
- Ganancia Bruta

**Tabla detallada**: Por comprobante — con desglose de base imponible, IGV, costo, margen.

**Exportación Excel**: Incluir hoja con resumen fiscal (útil para contador).

### 7.2 Gestión de Usuarios

> Idéntico a iziFact — tabla de usuarios, activar/desactivar, asignar roles.

### 7.3 Editor de Plantilla de Comprobante

> Idéntico a iziFact — editor HTML/CSS para personalizar el PDF.

**Archivos a crear en esta fase**:
- `app/blueprints/reportes/routes.py`
- `app/blueprints/admin/routes.py`
- `app/templates/reportes/ganancias.html`
- `app/templates/admin/usuarios.html`

---

## Fase 8 — Testing, Seguridad y Hardening

**Objetivo**: Asegurar la calidad del sistema antes del deploy a producción.

### 8.1 Tests Automatizados

```bash
tests/
├── conftest.py                   # App factory con BD de prueba, fixtures
├── test_models.py                # CRUD modelos, constraints, propiedades
├── test_igv_calculations.py      # Cálculos IGV con casos borde
│   ├── test_gravado_18_percent
│   ├── test_exonerado_zero_igv
│   ├── test_inafecto_zero_igv
│   ├── test_rounding_precision
│   └── test_envio_gravado
├── test_xml_generation.py        # XML UBL 2.1 estructura correcta
│   ├── test_factura_xml_structure
│   ├── test_boleta_xml_structure
│   ├── test_nc_xml_structure
│   ├── test_nd_xml_structure
│   ├── test_igv_totals_in_xml
│   └── test_customer_document_type_mapping
├── test_mipse_integration.py     # Mock MiPSE API
│   ├── test_token_refresh
│   ├── test_firmar_xml_success
│   ├── test_enviar_success
│   ├── test_duplicate_handling
│   └── test_consultar_estado_recovery
├── test_routes.py                # Endpoints principales
│   ├── test_login_required
│   ├── test_crear_factura
│   ├── test_crear_boleta
│   ├── test_emitir_nc
│   ├── test_emitir_nd
│   └── test_bulk_upload
├── test_pdf_generation.py        # PDF con IGV correcto
└── test_file_service.py          # Guardar/recuperar archivos
```

### 8.2 Checklist de Seguridad

- [x] CSRF tokens en todos los formularios (`Flask-WTF CSRFProtect`)
- [x] CSRF token en headers AJAX (`X-CSRFToken`)
- [x] Rate limiting en login (5/min), registro (3/hour), API (60/min)
- [x] Password hashing con Werkzeug `generate_password_hash`
- [x] SQL injection: prevenido por SQLAlchemy ORM (nunca raw SQL)
- [x] XSS: prevenido por Jinja2 auto-escaping
- [x] Validación server-side en TODOS los endpoints (no confiar en JS)
- [x] Headers de seguridad: X-Content-Type-Options, X-Frame-Options, CSP
- [x] HTTPS obligatorio en producción (via Easypanel/proxy)
- [x] Credenciales en variables de entorno (.env), nunca en código
- [x] `.gitignore`: .env, certificados/, comprobantes/, __pycache__/, uploads/
- [x] Whitelist de correos para registro
- [x] Permisos RBAC verificados en cada ruta protegida
- [x] Audit trail: `ultimo_login`, `ip_registro` en Usuario
- [x] Logging estructurado sin datos sensibles (no loguear passwords ni tokens)

### 8.3 Loading States Obligatorios

Toda operación asíncrona DEBE tener indicador visual:

| Operación | Indicador |
|---|---|
| Enviar a SUNAT | SweetAlert spinner + "Enviando comprobante a SUNAT..." |
| Emitir NC/ND | SweetAlert spinner + "Emitiendo nota..." |
| Carga masiva proceso | Modal con progress bar 0-100% + contadores éxito/error |
| NC lote | Modal con progress bar + "Procesando X de Y" |
| Buscar cliente DNI/RUC | Spinner en campo + "Consultando..." |
| Sync WooCommerce | Spinner en botón + "Sincronizando productos..." |
| Descarga PDF/XML/CDR | Spinner en botón durante generación |
| Login | Spinner en botón submit |
| Upload Excel | Spinner en botón + "Analizando..." |
| Importar CDRs | SweetAlert spinner + "Importando X archivo(s)..." |
| Recuperar CDRs masivo | SweetAlert spinner + "Consultando MiPSE..." |
| Eliminar comprobante | Confirm dialog + toast resultado |

---

## Fase 9 — Deployment a Producción

**Objetivo**: Configurar Docker, CI/CD y Easypanel para producción.

### 9.1 Dockerfile

```dockerfile
FROM python:3.11-slim

# Dependencias del sistema para ReportLab, lxml, WeasyPrint
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev libpq-dev \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Crear directorios de archivos
RUN mkdir -p comprobantes uploads

EXPOSE 80

CMD ["gunicorn", "--bind", "0.0.0.0:80", "--workers", "2", "--timeout", "600", "wsgi:app"]
```

### 9.2 docker-compose.yml (Desarrollo Local)

```yaml
version: '3.8'
services:
  web:
    build: .
    ports:
      - "5000:80"
    env_file: .env
    volumes:
      - ./comprobantes:/app/comprobantes
      - ./uploads:/app/uploads
    depends_on:
      - db

  db:
    image: postgres:15
    environment:
      POSTGRES_DB: mlfact
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5433:5432"

volumes:
  pgdata:
```

### 9.3 Easypanel — Volúmenes Persistentes (Lección Aprendida)

> **Lección crítica de iziFact**: Sin volúmenes, cada redeploy borra todos los CDR/XML/PDF guardados. Configurar desde el día 1.

| Mount Name | Container Path | Propósito |
|---|---|---|
| `mlfact-comprobantes` | `/app/comprobantes` | CDRs, XMLs firmados, PDFs |
| `mlfact-uploads` | `/app/uploads` | Archivos temporales de carga |
| `mlfact-certificados` | `/app/certificados` | Certificado digital .pfx |

### 9.4 Variables de Entorno (.env.example)

```env
# Flask
SECRET_KEY=cambiar-en-produccion
FLASK_ENV=production

# PostgreSQL (base de datos INDEPENDIENTE de iziFact)
DB_USER=postgres
DB_PASSWORD=
DB_HOST=mlfact-db
DB_PORT=5432
DB_NAME=mlfact

# WooCommerce MySQL (MISMO que iziFact - lectura)
WOO_DB_USER=root
WOO_DB_PASSWORD=
WOO_DB_HOST=localhost
WOO_DB_PORT=3306
WOO_DB_NAME=wordpress

# WooCommerce API (MISMO que iziFact)
WOO_URL=https://tienda.example.com
WOO_CONSUMER_KEY=ck_...
WOO_CONSUMER_SECRET=cs_...

# APIs Peru (MISMO token)
APISPERU_TOKEN=

# SUNAT
SUNAT_AMBIENTE=PRODUCCION
CERT_PATH=certificados/certificado_ml.pfx
CERT_PASSWORD=

# MiPSE (MISMO proveedor, credenciales de la nueva empresa)
MIPSE_URL=https://api.mipse.pe
MIPSE_SYSTEM=produccion
MIPSE_USUARIO=ml_import_user
MIPSE_PASSWORD=ml_import_pass

# Empresa
EMPRESA_RUC=20605555790
EMPRESA_RAZON_SOCIAL=M & L IMPORT EXPORT PERU S.A.C.
EMPRESA_NOMBRE_COMERCIAL=M & L Import Export
EMPRESA_DIRECCION=
EMPRESA_TELEFONO=
EMPRESA_EMAIL=
EMPRESA_UBIGEO=

# Series
SERIE_FACTURA=F001
SERIE_BOLETA=B001
SERIE_NC_FACTURA=FC01
SERIE_NC_BOLETA=BC01
SERIE_ND_FACTURA=FD01
SERIE_ND_BOLETA=BD01

# Horarios de envío automático
HORARIOS_ENVIO=21:00

# Correos autorizados para registro
AUTHORIZED_EMAILS=admin@mlimport.com,ventas@mlimport.com
```

### 9.5 Health Check

```python
@app.route('/health')
def health():
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({'status': 'ok', 'database': 'connected'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'database': str(e)}), 500
```

---

## Fase 10 — Monitoreo, Logging y Mantenimiento

### 10.1 Logging Estructurado

```python
import logging
import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger()

# Uso:
logger.info("comprobante_enviado",
    comprobante=comprobante.numero_completo,
    tipo=comprobante.tipo_comprobante,
    estado=resultado['estado'],
    mipse_response_code=resultado.get('response_code'))
```

### 10.2 Monitoreo

- Health check endpoint (`/health`) para Easypanel
- Logging de todas las operaciones SUNAT con response codes
- Alertas por comprobantes rechazados (email o webhook futuro)
- Dashboard muestra rechazados en rojo para atención inmediata

### 10.3 Mantenimiento

- **Script de recuperación**: `scripts/heal_cdrs.py` — recuperar CDRs faltantes de MiPSE
- **Backup de BD**: Configurar backup automático en Easypanel/PostgreSQL
- **Importación manual**: Página `/importar-cdrs` para subir CDR/XML manualmente

---

## Resumen de Lecciones Aprendidas Aplicadas

| # | Problema en iziFact | Solución en MLFact |
|---|---|---|
| 1 | Monolito `app.py` (2744 líneas) | Flask Blueprints modularizados |
| 2 | Sin Flask-Migrate, scripts manuales | Flask-Migrate (Alembic) desde día 1 |
| 3 | `enviar_lote` usaba `resultado.get('cdr_path')` (None) | `file_service.guardar_archivos()` en TODOS los flujos |
| 4 | Docker sin volúmenes = pérdida de archivos | Volúmenes configurados desde día 1 |
| 5 | Sin CSRF explícito | Flask-WTF CSRFProtect en todas las rutas |
| 6 | `{% block scripts %}` vs `{% block extra_js %}` | Convención documentada: `{% block extra_js %}` |
| 7 | Correlativo como VARCHAR con bugs de tipo | Tipo consistente `String(10)`, formato `zfill(8)` solo para SUNAT |
| 8 | ENVIO como ítem Y como campo | SOLO como campo `costo_envio`, nunca como ítem |
| 9 | Scheduler con file lock | Lock basado en base de datos |
| 10 | Sin tests automatizados | Pytest desde el inicio con cobertura de IGV y XML |
| 11 | Fechas confusas (pedido vs emisión) | Campos claros: `fecha_pedido` (WooCommerce), `fecha_emision` (SUNAT) |
| 12 | JS inline en templates | Scripts compartidos extraídos a `static/js/` |
| 13 | Sin logging estructurado | structlog con JSON desde día 1 |
| 14 | `AddressTypeCode` olvidado en NC | Template XML completo desde inicio para todos los tipos |
| 15 | Sin rate limiting | Flask-Limiter configurado |

---

## Verificación y Testing End-to-End

### Ambiente BETA

1. Configurar `SUNAT_AMBIENTE=BETA` y `MIPSE_SYSTEM=beta`
2. Crear admin: `python scripts/create_admin.py`
3. Seed RBAC: `python scripts/seed_rbac.py`
4. Sync WooCommerce: `python scripts/sync_woo.py`
5. Login → Dashboard → verificar indicadores
6. Nueva Venta → seleccionar cliente RUC → verificar que dice "FACTURA F001"
7. Agregar ítems → verificar cálculo IGV en tiempo real
8. Emitir → verificar XML generado (estructura, IGV, totales)
9. Verificar CDR guardado en `comprobantes/`
10. Descargar PDF → verificar desglose IGV
11. Emitir NC → verificar XML NC con referencia
12. Emitir ND → verificar XML ND con referencia
13. Bulk upload → verificar determinación Factura/Boleta automática
14. Ejecutar `pytest tests/` → todos green

### Ambiente PRODUCCION

1. Cambiar `SUNAT_AMBIENTE=PRODUCCION` y `MIPSE_SYSTEM=produccion`
2. Verificar certificado digital de M & L
3. Verificar credenciales MiPSE de la nueva empresa
4. Deploy en Easypanel con volúmenes configurados
5. Emitir primera factura de prueba
6. Verificar en portal SUNAT que aparezca el comprobante
7. Redeploy y verificar que archivos persisten (volúmenes)

---

## Archivos Críticos de Referencia (Proyecto Actual)

Estos archivos del proyecto iziFact sirven como base de referencia:

| Archivo iziFact | Uso en MLFact |
|---|---|
| `services/sunat_service.py` | Base para `sunat_xml_service.py` — adaptar de inafecto a gravado |
| `services/mipse_service.py` | Copiar casi idéntico, solo cambiar credenciales |
| `services/pdf_service.py` | Base para nuevo `pdf_service.py` — agregar desglose IGV |
| `services/scheduler_service.py` | Base, mejorar con DB lock |
| `services/utils.py` | Reutilizar `number_to_words_es`, `extraer_skus_base` |
| `models.py` | Base para modelos en `app/models/` — agregar campos IGV |
| `config.py` | Base para `app/config.py` — agregar series F/ND |
| `templates/base.html` | Base para nuevo layout — rebranding MLFact |
| `templates/nueva_venta.html` | Base para POS — agregar badge tipo comprobante + IGV |
| `templates/ventas_list.html` | Base para lista — agregar filtro tipo + columna IGV |
| `app.py:guardar_archivos_mipse()` | Extraer a `file_service.py` |
