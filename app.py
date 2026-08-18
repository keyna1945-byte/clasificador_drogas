from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify, session
import sqlite3
import pandas as pd
import os
import base64
import requests
from io import BytesIO
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or "clave_secreta"

API_KEY = os.getenv("GOOGLE_API_KEY") or "TU_API_KEY_AQUI"
ROLES = ("admin", "tecnico", "consulta")


def fecha_actual():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conectar_db():
    ruta_local = os.path.join(os.path.dirname(__file__), "sustancias.db")
    ruta_render = "/var/data/sustancias.db"
    ruta_db = ruta_render if os.path.isdir("/var/data") and os.access("/var/data", os.W_OK) else ruta_local

    conn = sqlite3.connect(ruta_db)
    conn.row_factory = sqlite3.Row
    return conn


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login", siguiente=request.path))
        return func(*args, **kwargs)
    return wrapper


def roles_required(*roles):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "usuario_id" not in session:
                return redirect(url_for("login", siguiente=request.path))

            if session.get("rol") not in roles:
                flash("No tenes permiso para realizar esa accion.")
                return redirect(url_for("index"))

            return func(*args, **kwargs)
        return wrapper
    return decorator


def registrar_inicio_sesion(usuario_id, usuario, exitoso, detalle=""):
    with conectar_db() as conn:
        conn.execute("""
            INSERT INTO login_logs (
                usuario_id,
                usuario,
                fecha,
                ip,
                exitoso,
                detalle
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            usuario_id,
            usuario,
            fecha_actual(),
            request.headers.get("X-Forwarded-For", request.remote_addr),
            1 if exitoso else 0,
            detalle
        ))
        conn.commit()


@app.context_processor
def contexto_usuario():
    return {
        "usuario_nombre": session.get("usuario"),
        "usuario_rol": session.get("rol")
    }


# ---------------------------------------------------------
# MIGRACION SEGURA DEL ESQUEMA
# ---------------------------------------------------------

def asegurar_columnas(conn, tabla, columnas):
    existentes = {
        fila["name"]
        for fila in conn.execute(f"PRAGMA table_info({tabla})").fetchall()
    }

    for nombre, definicion in columnas.items():
        if nombre not in existentes:
            conn.execute(
                f"ALTER TABLE {tabla} ADD COLUMN {nombre} {definicion}"
            )


def crear_tabla():
    with conectar_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS drogas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero INTEGER,
                nombre TEXT NOT NULL,
                peligros TEXT,
                cancerigeno TEXT,
                cantidad TEXT,
                ubicacion TEXT
            )
        """)

        columnas_seguridad = {
            "cas": "TEXT",
            "fabricante": "TEXT",
            "concentracion": "TEXT",
            "formulacion": "TEXT",
            "nombre_normalizado": "TEXT",
            "tipo_registro": "TEXT",
            "prioridad_verificacion": "TEXT",
            "motivo_prioridad": "TEXT",
            "inflamable_combustible": "TEXT",
            "corrosivo": "TEXT",
            "oxidante": "TEXT",
            "toxicidad": "TEXT",
            "carcinogenicidad_verificada": "TEXT",
            "pictogramas_ghs": "TEXT",
            "frases_h": "TEXT",
            "epp": "TEXT",
            "manipulacion_segura": "TEXT",
            "almacenamiento_seguro": "TEXT",
            "derrames": "TEXT",
            "observaciones_seguridad": "TEXT",
            "fuente_seguridad": "TEXT",
            "estado_verificacion": "TEXT DEFAULT 'Pendiente'",
            "ultima_revision": "TEXT"
        }

        asegurar_columnas(
            conn,
            "drogas",
            columnas_seguridad
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                rol TEXT NOT NULL DEFAULT 'consulta',
                activo INTEGER NOT NULL DEFAULT 0,
                creado_en TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS login_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER,
                usuario TEXT,
                fecha TEXT NOT NULL,
                ip TEXT,
                exitoso INTEGER NOT NULL,
                detalle TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS movimientos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                droga_id INTEGER NOT NULL,
                usuario_id INTEGER,
                accion TEXT NOT NULL,
                cantidad TEXT,
                observacion TEXT,
                fecha TEXT NOT NULL,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
        """)

        cantidad_usuarios = conn.execute(
            "SELECT COUNT(*) FROM usuarios"
        ).fetchone()[0]

        if cantidad_usuarios == 0:
            conn.execute("""
                INSERT INTO usuarios (
                    usuario,
                    password_hash,
                    rol,
                    activo,
                    creado_en
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                "admin",
                generate_password_hash("admin123"),
                "admin",
                1,
                fecha_actual()
            ))

        conn.commit()


crear_tabla()


# ---------------------------------------------------------
# AUTENTICACION
# ---------------------------------------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form.get(
            'usuario',
            ''
        ).strip()

        password = request.form.get(
            'password',
            ''
        )

        with conectar_db() as conn:
            cuenta = conn.execute(
                """
                SELECT *
                FROM usuarios
                WHERE usuario=?
                """,
                (usuario,)
            ).fetchone()

        if not cuenta:
            registrar_inicio_sesion(
                None,
                usuario,
                False,
                "Usuario inexistente"
            )

            flash(
                "Usuario o contrasena incorrectos."
            )

            return redirect(
                url_for('login')
            )

        if not cuenta['activo']:
            registrar_inicio_sesion(
                cuenta['id'],
                usuario,
                False,
                "Usuario pendiente o inactivo"
            )

            flash(
                "Tu usuario todavia no esta activo. Consultale al administrador."
            )

            return redirect(
                url_for('login')
            )

        if not check_password_hash(
            cuenta['password_hash'],
            password
        ):
            registrar_inicio_sesion(
                cuenta['id'],
                usuario,
                False,
                "Contrasena incorrecta"
            )

            flash(
                "Usuario o contrasena incorrectos."
            )

            return redirect(
                url_for('login')
            )

        session.clear()
        session['usuario_id'] = cuenta['id']
        session['usuario'] = cuenta['usuario']
        session['rol'] = cuenta['rol']

        registrar_inicio_sesion(
            cuenta['id'],
            usuario,
            True,
            "Inicio correcto"
        )

        return redirect(
            request.args.get('siguiente')
            or url_for('index')
        )

    return render_template(
        'login.html'
    )


@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        usuario = request.form.get(
            'usuario',
            ''
        ).strip()

        password = request.form.get(
            'password',
            ''
        )

        if not usuario or not password:
            flash(
                "Completa usuario y contrasena."
            )

            return redirect(
                url_for('registro')
            )

        try:
            with conectar_db() as conn:
                conn.execute("""
                    INSERT INTO usuarios (
                        usuario,
                        password_hash,
                        rol,
                        activo,
                        creado_en
                    )
                    VALUES (?, ?, 'consulta', 0, ?)
                """, (
                    usuario,
                    generate_password_hash(password),
                    fecha_actual()
                ))

                conn.commit()

        except sqlite3.IntegrityError:
            flash(
                "Ese usuario ya existe."
            )

            return redirect(
                url_for('registro')
            )

        flash(
            "Usuario creado. Un administrador debe activarlo y asignar el rol."
        )

        return redirect(
            url_for('login')
        )

    return render_template(
        'registro.html'
    )


@app.route('/logout')
def logout():
    session.clear()

    flash(
        "Sesion cerrada."
    )

    return redirect(
        url_for('login')
    )


# ---------------------------------------------------------
# INVENTARIO
# ---------------------------------------------------------

@app.route('/')
@login_required
def index():
    busqueda = request.args.get(
        'busqueda',
        ''
    ).strip()

    with conectar_db() as conn:
        if busqueda:
            patron = f'%{busqueda}%'

            cursor = conn.execute("""
                SELECT
                    rowid AS droga_rowid,
                    *
                FROM drogas
                WHERE CAST(numero AS TEXT) LIKE ?
                   OR nombre LIKE ?
                   OR peligros LIKE ?
                   OR ubicacion LIKE ?
                   OR cantidad LIKE ?
                   OR cas LIKE ?
                   OR inflamable_combustible LIKE ?
                   OR corrosivo LIKE ?
                   OR carcinogenicidad_verificada LIKE ?
                ORDER BY nombre ASC
            """, (
                patron,
                patron,
                patron,
                patron,
                patron,
                patron,
                patron,
                patron,
                patron
            ))

        else:
            cursor = conn.execute("""
                SELECT
                    rowid AS droga_rowid,
                    *
                FROM drogas
                ORDER BY nombre ASC
            """)

        drogas = cursor.fetchall()

    return render_template(
        'index.html',
        drogas=drogas,
        busqueda=busqueda
    )


# ---------------------------------------------------------
# MOVIMIENTOS
# ---------------------------------------------------------

def cargar_movimientos(
    conn,
    droga_rowid
):
    return conn.execute("""
        SELECT
            m.*,
            u.usuario
        FROM movimientos m
        LEFT JOIN usuarios u
            ON u.id = m.usuario_id
        WHERE m.droga_id=?
        ORDER BY
            m.fecha DESC,
            m.rowid DESC
        LIMIT 100
    """, (
        droga_rowid,
    )).fetchall()


def registrar_movimiento(
    conn,
    droga_rowid,
    accion,
    cantidad="",
    observacion=""
):
    conn.execute("""
        INSERT INTO movimientos (
            droga_id,
            usuario_id,
            accion,
            cantidad,
            observacion,
            fecha
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        droga_rowid,
        session.get('usuario_id'),
        accion,
        cantidad,
        observacion,
        fecha_actual()
    ))


# ---------------------------------------------------------
# FICHA DE SUSTANCIA
# ---------------------------------------------------------

@app.route(
    '/sustancia/<int:numero>',
    methods=['GET', 'POST']
)
@login_required
def ficha_sustancia(numero):
    with conectar_db() as conn:
        cursor = conn.execute("""
            SELECT
                rowid AS droga_rowid,
                *
            FROM drogas
            WHERE numero=?
        """, (
            numero,
        ))

        droga = cursor.fetchone()

        if not droga:
            flash(
                "Sustancia no encontrada."
            )

            return redirect(
                url_for('index')
            )

        if request.method == 'POST':
            if session.get("rol") not in (
                "admin",
                "tecnico"
            ):
                flash(
                    "No tenes permiso para modificar movimientos o cantidades."
                )

                return redirect(
                    url_for(
                        'ficha_sustancia',
                        numero=numero
                    )
                )

            tipo = request.form.get(
                'tipo',
                ''
            ).strip()

            # ---------------------------------
            # ACTUALIZAR CANTIDAD
            # ---------------------------------
            if tipo == 'cantidad':
                cantidad_anterior = (
                    droga['cantidad'] or ''
                )

                cantidad_nueva = request.form.get(
                    'cantidad',
                    ''
                ).strip()

                conn.execute("""
                    UPDATE drogas
                    SET cantidad=?
                    WHERE rowid=?
                """, (
                    cantidad_nueva,
                    droga['droga_rowid']
                ))

                observacion = (
                    f"Cantidad modificada: "
                    f"{cantidad_anterior or 'Sin dato'} "
                    f"→ "
                    f"{cantidad_nueva or 'Sin dato'}"
                )

                registrar_movimiento(
                    conn,
                    droga['droga_rowid'],
                    'actualizacion de cantidad',
                    cantidad_nueva,
                    observacion
                )

                conn.commit()

                flash(
                    "Cantidad actualizada correctamente."
                )

                return redirect(
                    url_for(
                        'ficha_sustancia',
                        numero=numero
                    )
                )

            # ---------------------------------
            # MOVIMIENTO MANUAL
            # ---------------------------------
            if tipo == 'movimiento':
                accion = request.form.get(
                    'accion',
                    ''
                ).strip()

                cantidad_movimiento = request.form.get(
                    'cantidad_movimiento',
                    ''
                ).strip()

                observacion = request.form.get(
                    'observacion',
                    ''
                ).strip()

                acciones_validas = (
                    'retirado',
                    'en uso',
                    'devuelto'
                )

                if accion not in acciones_validas:
                    flash(
                        "Selecciona una accion valida."
                    )

                    return redirect(
                        url_for(
                            'ficha_sustancia',
                            numero=numero
                        )
                    )

                registrar_movimiento(
                    conn,
                    droga['droga_rowid'],
                    accion,
                    cantidad_movimiento,
                    observacion
                )

                conn.commit()

                flash(
                    "Movimiento registrado correctamente."
                )

                return redirect(
                    url_for(
                        'ficha_sustancia',
                        numero=numero
                    )
                )

            flash(
                "No se pudo identificar la operacion."
            )

            return redirect(
                url_for(
                    'ficha_sustancia',
                    numero=numero
                )
            )

        movimientos = cargar_movimientos(
            conn,
            droga['droga_rowid']
        )

    return render_template(
        'sustancia.html',
        droga=droga,
        movimientos=movimientos
    )


# ---------------------------------------------------------
# USUARIOS
# ---------------------------------------------------------

@app.route(
    '/usuarios',
    methods=['GET', 'POST']
)
@roles_required("admin")
def usuarios():
    if request.method == 'POST':
        usuario = request.form.get(
            'usuario',
            ''
        ).strip()

        password = request.form.get(
            'password',
            ''
        )

        rol = request.form.get(
            'rol',
            'consulta'
        )

        activo = (
            1
            if request.form.get('activo') == 'on'
            else 0
        )

        if rol not in ROLES:
            rol = 'consulta'

        try:
            with conectar_db() as conn:
                conn.execute("""
                    INSERT INTO usuarios (
                        usuario,
                        password_hash,
                        rol,
                        activo,
                        creado_en
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    usuario,
                    generate_password_hash(password),
                    rol,
                    activo,
                    fecha_actual()
                ))

                conn.commit()

            flash(
                "Usuario creado correctamente."
            )

        except sqlite3.IntegrityError:
            flash(
                "Ese usuario ya existe."
            )

        return redirect(
            url_for('usuarios')
        )

    with conectar_db() as conn:
        lista_usuarios = conn.execute("""
            SELECT *
            FROM usuarios
            ORDER BY usuario ASC
        """).fetchall()

    return render_template(
        'usuarios.html',
        usuarios=lista_usuarios,
        roles=ROLES
    )


@app.route(
    '/usuarios/<int:id>/actualizar',
    methods=['POST']
)
@roles_required("admin")
def actualizar_usuario(id):
    rol = request.form.get(
        'rol',
        'consulta'
    )

    activo = (
        1
        if request.form.get('activo') == 'on'
        else 0
    )

    nueva_password = request.form.get(
        'password',
        ''
    )

    if rol not in ROLES:
        rol = 'consulta'

    with conectar_db() as conn:
        if nueva_password:
            conn.execute("""
                UPDATE usuarios
                SET
                    rol=?,
                    activo=?,
                    password_hash=?
                WHERE id=?
            """, (
                rol,
                activo,
                generate_password_hash(
                    nueva_password
                ),
                id
            ))

        else:
            conn.execute("""
                UPDATE usuarios
                SET
                    rol=?,
                    activo=?
                WHERE id=?
            """, (
                rol,
                activo,
                id
            ))

        conn.commit()

    flash(
        "Usuario actualizado."
    )

    return redirect(
        url_for('usuarios')
    )


# ---------------------------------------------------------
# HISTORIAL GENERAL
# ---------------------------------------------------------

@app.route('/historial')
@roles_required("admin")
def historial():
    with conectar_db() as conn:
        logs = conn.execute("""
            SELECT *
            FROM login_logs
            ORDER BY
                fecha DESC,
                id DESC
            LIMIT 200
        """).fetchall()

        movimientos = conn.execute("""
            SELECT
                m.*,
                d.numero,
                d.nombre,
                u.usuario
            FROM movimientos m
            JOIN drogas d
                ON d.rowid = m.droga_id
            LEFT JOIN usuarios u
                ON u.id = m.usuario_id
            ORDER BY
                m.fecha DESC,
                m.rowid DESC
            LIMIT 500
        """).fetchall()

    return render_template(
        'historial.html',
        logs=logs,
        movimientos=movimientos
    )


# ---------------------------------------------------------
# CAMPOS DE SUSTANCIA
# ---------------------------------------------------------

def obtener_campos_sustancia(form):
    return {
        'numero': form.get(
            'numero',
            ''
        ).strip(),

        'nombre': form.get(
            'nombre',
            ''
        ).strip(),

        'peligros': form.get(
            'peligros',
            ''
        ).strip(),

        'cancerigeno': form.get(
            'cancerigeno',
            ''
        ).strip(),

        'cantidad': form.get(
            'cantidad',
            ''
        ).strip(),

        'ubicacion': form.get(
            'ubicacion',
            ''
        ).strip(),

        'cas': form.get(
            'cas',
            ''
        ).strip(),

        'fabricante': form.get(
            'fabricante',
            ''
        ).strip(),

        'concentracion': form.get(
            'concentracion',
            ''
        ).strip(),

        'formulacion': form.get(
            'formulacion',
            ''
        ).strip(),

        'nombre_normalizado': form.get(
            'nombre_normalizado',
            ''
        ).strip(),

        'tipo_registro': form.get(
            'tipo_registro',
            ''
        ).strip(),

        'prioridad_verificacion': form.get(
            'prioridad_verificacion',
            ''
        ).strip(),

        'motivo_prioridad': form.get(
            'motivo_prioridad',
            ''
        ).strip(),

        'inflamable_combustible': form.get(
            'inflamable_combustible',
            ''
        ).strip(),

        'corrosivo': form.get(
            'corrosivo',
            ''
        ).strip(),

        'oxidante': form.get(
            'oxidante',
            ''
        ).strip(),

        'toxicidad': form.get(
            'toxicidad',
            ''
        ).strip(),

        'carcinogenicidad_verificada': form.get(
            'carcinogenicidad_verificada',
            ''
        ).strip(),

        'pictogramas_ghs': form.get(
            'pictogramas_ghs',
            ''
        ).strip(),

        'frases_h': form.get(
            'frases_h',
            ''
        ).strip(),

        'epp': form.get(
            'epp',
            ''
        ).strip(),

        'manipulacion_segura': form.get(
            'manipulacion_segura',
            ''
        ).strip(),

        'almacenamiento_seguro': form.get(
            'almacenamiento_seguro',
            ''
        ).strip(),

        'derrames': form.get(
            'derrames',
            ''
        ).strip(),

        'observaciones_seguridad': form.get(
            'observaciones_seguridad',
            ''
        ).strip(),

        'fuente_seguridad': form.get(
            'fuente_seguridad',
            ''
        ).strip(),

        'estado_verificacion': form.get(
            'estado_verificacion',
            'Pendiente'
        ).strip(),

        'ultima_revision': form.get(
            'ultima_revision',
            ''
        ).strip()
    }


def normalizar_valor(valor):
    if valor is None:
        return ''

    return str(valor).strip()


def obtener_cambios_edicion(
    droga,
    campos
):
    etiquetas = {
        'numero': 'Numero',
        'nombre': 'Nombre',
        'cantidad': 'Cantidad',
        'ubicacion': 'Ubicacion',
        'cas': 'CAS',
        'fabricante': 'Fabricante',
        'concentracion': 'Concentracion',
        'formulacion': 'Formulacion',
        'nombre_normalizado': 'Nombre normalizado',
        'tipo_registro': 'Tipo de registro',
        'peligros': 'Peligros',
        'cancerigeno': 'Cancerigeno historico',
        'inflamable_combustible': 'Inflamable / combustible',
        'corrosivo': 'Corrosivo',
        'oxidante': 'Oxidante',
        'toxicidad': 'Toxicidad',
        'carcinogenicidad_verificada': 'Carcinogenicidad',
        'pictogramas_ghs': 'Pictogramas GHS',
        'frases_h': 'Frases H',
        'epp': 'EPP',
        'manipulacion_segura': 'Manipulacion segura',
        'almacenamiento_seguro': 'Almacenamiento seguro',
        'derrames': 'Derrames',
        'observaciones_seguridad': 'Observaciones de seguridad',
        'fuente_seguridad': 'Fuente de seguridad',
        'prioridad_verificacion': 'Prioridad de verificacion',
        'motivo_prioridad': 'Motivo de prioridad',
        'estado_verificacion': 'Estado de verificacion',
        'ultima_revision': 'Ultima revision'
    }

    cambios = []

    for campo, etiqueta in etiquetas.items():
        anterior = normalizar_valor(
            droga[campo]
        )

        nuevo = normalizar_valor(
            campos.get(campo)
        )

        if anterior != nuevo:
            anterior_mostrar = (
                anterior
                if anterior
                else 'Sin dato'
            )

            nuevo_mostrar = (
                nuevo
                if nuevo
                else 'Sin dato'
            )

            cambios.append(
                f"{etiqueta}: "
                f"{anterior_mostrar} "
                f"→ "
                f"{nuevo_mostrar}"
            )

    return cambios


# ---------------------------------------------------------
# AGREGAR
# ---------------------------------------------------------

@app.route(
    '/agregar',
    methods=['GET', 'POST']
)
@roles_required(
    "admin",
    "tecnico"
)
def agregar():
    if request.method == 'POST':
        campos = obtener_campos_sustancia(
            request.form
        )

        if not campos['nombre']:
            flash(
                "El nombre es obligatorio."
            )

            return redirect(
                url_for('agregar')
            )

        with conectar_db() as conn:
            conn.execute("""
                INSERT INTO drogas (
                    numero,
                    nombre,
                    peligros,
                    cancerigeno,
                    cantidad,
                    ubicacion,
                    cas,
                    fabricante,
                    concentracion,
                    formulacion,
                    nombre_normalizado,
                    tipo_registro,
                    prioridad_verificacion,
                    motivo_prioridad,
                    inflamable_combustible,
                    corrosivo,
                    oxidante,
                    toxicidad,
                    carcinogenicidad_verificada,
                    pictogramas_ghs,
                    frases_h,
                    epp,
                    manipulacion_segura,
                    almacenamiento_seguro,
                    derrames,
                    observaciones_seguridad,
                    fuente_seguridad,
                    estado_verificacion,
                    ultima_revision
                )
                VALUES (
                    :numero,
                    :nombre,
                    :peligros,
                    :cancerigeno,
                    :cantidad,
                    :ubicacion,
                    :cas,
                    :fabricante,
                    :concentracion,
                    :formulacion,
                    :nombre_normalizado,
                    :tipo_registro,
                    :prioridad_verificacion,
                    :motivo_prioridad,
                    :inflamable_combustible,
                    :corrosivo,
                    :oxidante,
                    :toxicidad,
                    :carcinogenicidad_verificada,
                    :pictogramas_ghs,
                    :frases_h,
                    :epp,
                    :manipulacion_segura,
                    :almacenamiento_seguro,
                    :derrames,
                    :observaciones_seguridad,
                    :fuente_seguridad,
                    :estado_verificacion,
                    :ultima_revision
                )
            """, campos)

            nuevo_rowid = conn.execute(
                "SELECT last_insert_rowid()"
            ).fetchone()[0]

            registrar_movimiento(
                conn,
                nuevo_rowid,
                'alta de sustancia',
                campos['cantidad'],
                'Sustancia agregada al inventario.'
            )

            conn.commit()

        flash(
            "Sustancia agregada correctamente."
        )

        return redirect(
            url_for('index')
        )

    return render_template(
        'agregar.html'
    )


# ---------------------------------------------------------
# EDITAR + AUDITORIA AUTOMATICA
# ---------------------------------------------------------

@app.route(
    '/editar/<int:id>',
    methods=['GET', 'POST']
)
@roles_required(
    "admin",
    "tecnico"
)
def editar(id):
    with conectar_db() as conn:
        droga = conn.execute("""
            SELECT
                rowid AS droga_rowid,
                *
            FROM drogas
            WHERE rowid=?
        """, (
            id,
        )).fetchone()

        if not droga:
            flash(
                "Sustancia no encontrada."
            )

            return redirect(
                url_for('index')
            )

        if request.method == 'POST':
            campos = obtener_campos_sustancia(
                request.form
            )

            campos['rowid'] = id

            if not campos['nombre']:
                flash(
                    "El nombre es obligatorio."
                )

                return redirect(
                    url_for(
                        'editar',
                        id=id
                    )
                )

            cambios = obtener_cambios_edicion(
                droga,
                campos
            )

            conn.execute("""
                UPDATE drogas
                SET
                    ubicacion=:ubicacion,
                    nombre=:nombre,
                    numero=:numero,
                    cantidad=:cantidad,
                    peligros=:peligros,
                    cancerigeno=:cancerigeno,
                    cas=:cas,
                    fabricante=:fabricante,
                    concentracion=:concentracion,
                    formulacion=:formulacion,
                    nombre_normalizado=:nombre_normalizado,
                    tipo_registro=:tipo_registro,
                    prioridad_verificacion=:prioridad_verificacion,
                    motivo_prioridad=:motivo_prioridad,
                    inflamable_combustible=:inflamable_combustible,
                    corrosivo=:corrosivo,
                    oxidante=:oxidante,
                    toxicidad=:toxicidad,
                    carcinogenicidad_verificada=:carcinogenicidad_verificada,
                    pictogramas_ghs=:pictogramas_ghs,
                    frases_h=:frases_h,
                    epp=:epp,
                    manipulacion_segura=:manipulacion_segura,
                    almacenamiento_seguro=:almacenamiento_seguro,
                    derrames=:derrames,
                    observaciones_seguridad=:observaciones_seguridad,
                    fuente_seguridad=:fuente_seguridad,
                    estado_verificacion=:estado_verificacion,
                    ultima_revision=:ultima_revision
                WHERE rowid=:rowid
            """, campos)

            if cambios:
                registrar_movimiento(
                    conn,
                    id,
                    'edicion',
                    campos['cantidad'],
                    " | ".join(cambios)
                )

            conn.commit()

            if cambios:
                flash(
                    "Cambios guardados y registrados en el historial."
                )
            else:
                flash(
                    "No se detectaron cambios."
                )

            return redirect(
                url_for('index')
            )

    return render_template(
        'editar.html',
        droga=droga
    )


# ---------------------------------------------------------
# ELIMINAR
# ---------------------------------------------------------

@app.route(
    '/eliminar/<int:id>'
)
@roles_required("admin")
def eliminar(id):
    with conectar_db() as conn:
        droga = conn.execute("""
            SELECT
                rowid AS droga_rowid,
                *
            FROM drogas
            WHERE rowid=?
        """, (
            id,
        )).fetchone()

        if not droga:
            flash(
                "Sustancia no encontrada."
            )

            return redirect(
                url_for('index')
            )

        # Se conserva el historial de movimientos,
        # pero se elimina la sustancia del inventario.
        conn.execute("""
            DELETE FROM drogas
            WHERE rowid=?
        """, (
            id,
        ))

        conn.commit()

    flash(
        "Sustancia eliminada correctamente."
    )

    return redirect(
        url_for('index')
    )


# ---------------------------------------------------------
# EXPORTAR EXCEL
# ---------------------------------------------------------

@app.route('/exportar_excel')
@login_required
def exportar_excel():
    with conectar_db() as conn:
        df = pd.read_sql_query("""
            SELECT
                rowid AS droga_rowid,
                *
            FROM drogas
            ORDER BY nombre ASC
        """, conn)

    output = BytesIO()

    df.to_excel(
        output,
        index=False,
        engine='openpyxl'
    )

    output.seek(0)

    return send_file(
        output,
        download_name="sustancias_exportadas.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ---------------------------------------------------------
# DETECCION DE TEXTO
# ---------------------------------------------------------

@app.route(
    '/detectar_texto',
    methods=['POST']
)
@login_required
def detectar_texto():
    if 'image' not in request.files:
        return jsonify({
            'error': 'No se subio ninguna imagen'
        }), 400

    imagen = request.files['image']

    contenido = base64.b64encode(
        imagen.read()
    ).decode()

    url = (
        "https://vision.googleapis.com/"
        f"v1/images:annotate?key={API_KEY}"
    )

    data = {
        "requests": [
            {
                "image": {
                    "content": contenido
                },
                "features": [
                    {
                        "type": "TEXT_DETECTION"
                    }
                ]
            }
        ]
    }

    response = requests.post(
        url,
        json=data
    )

    resultado = response.json()

    try:
        texto = (
            resultado['responses'][0]
            ['textAnnotations'][0]
            ['description']
        )

    except (
        KeyError,
        IndexError
    ):
        texto = (
            "No se detecto texto."
        )

    flash(
        f"Texto detectado: {texto}"
    )

    return redirect(
        url_for('index')
    )


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True)