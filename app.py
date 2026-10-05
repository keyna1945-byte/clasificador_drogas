from flask import Flask, render_template, request, redirect, url_for, flash, send_file, send_from_directory, jsonify, session
import sqlite3
import pandas as pd
import os
import base64
import requests
import unicodedata
from io import BytesIO
from datetime import datetime
from copy import copy
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from openpyxl import load_workbook

app = Flask(__name__)
@app.route('/service-worker.js')
def service_worker():
    return send_from_directory(
        app.static_folder,
        'service-worker.js',
        mimetype='application/javascript'
    )
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



# =========================================================
# MODULO RENPRE
# =========================================================

# IMPORTANTE:
# Los stocks iniciales de esta lista corresponden al saldo base de la
# planilla LIBIM T1 2026. La fecha base se conserva para que los informes
# de trimestres posteriores reconstruyan correctamente su stock de apertura.
RENPRE_FECHA_STOCK_BASE = os.getenv(
    "RENPRE_FECHA_STOCK_BASE",
    "2026-01-01"
)

RENPRE_PLANTILLA = os.getenv(
    "RENPRE_PLANTILLA",
    os.path.join(
        os.path.dirname(__file__),
        "RENPRE_LIBIM_PLANTILLA.xlsx"
    )
)

RENPRE_SUSTANCIAS_INICIALES = [
    ("Ácido clorhídrico", 1.0, "L"),
    ("Ácido sulfúrico", 6.0, "x1L"),
    ("Permanganato de potasio", 1.0, "x 250g"),
    ("Tolueno", 0.5, "x1L"),
    ("Cloroformo", 0.5, "x1L"),
    ("Éter etílico", 7.0, "x1L"),
    ("Acetona", 1.0, "x1L"),
    ("Hidróxido de sodio", 5.0, "x 500g"),
    ("Hidróxido de potasio", 1.0, "x 500g"),
    ("Sulfato de sodio", 2.0, "x 500g"),
    ("Carbonato de sodio", 2.0, "x500g"),
    ("Hexano", 1.0, "x1L"),
    ("Xilenos", 0.0, ""),
    ("Ácido acético", 3.0, "x1L"),
    ("Hidróxido de calcio", 1.0, "x500g"),
    ("Alcohol etílico", 2.0, "x1L"),
    ("Cloruro de amonio", 1.0, "x 500g"),
    ("Nitrito de sodio", 1.0, "x 250g"),
    ("Bicarbonato de sodio", 2.0, "x 500g"),
    ("Cianuro de potasio", 1.0, "x 500g"),
    ("Alcohol metílico", 1.0, "x1L"),
    ("Alcohol isopropílico", 1.0, "x1L"),
    ("Alcohol n-butílico", 1.0, "x1L"),
    ("Alcohol isobutílico", 1.0, "x1L"),
]


def normalizar_nombre_renpre(texto):
    texto = (texto or "").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        c for c in texto
        if not unicodedata.combining(c)
    )
    texto = " ".join(texto.split())
    return texto


def normalizar_unidad_renpre(unidad):
    return " ".join((unidad or "").strip().lower().split())


def fecha_renpre_valida(fecha):
    try:
        datetime.strptime(fecha, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def crear_tablas_renpre():
    with conectar_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS renpre_sustancias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                droga_rowid INTEGER,
                nombre_renpre TEXT UNIQUE NOT NULL,
                activo INTEGER NOT NULL DEFAULT 1,
                stock_inicial REAL NOT NULL DEFAULT 0,
                unidad_stock TEXT,
                fecha_stock_inicial TEXT,
                observacion TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS renpre_movimientos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                renpre_sustancia_id INTEGER NOT NULL,
                usuario_id INTEGER,
                fecha TEXT NOT NULL,
                tipo_operacion TEXT NOT NULL,
                sentido TEXT NOT NULL,
                cantidad REAL NOT NULL,
                unidad TEXT,
                documento_tipo TEXT,
                documento_numero TEXT,
                transportista TEXT,
                remitente_destinatario TEXT,
                titular_dni TEXT,
                observacion TEXT,
                creado_en TEXT NOT NULL,
                anulado INTEGER NOT NULL DEFAULT 0,
                anulado_en TEXT,
                anulado_por INTEGER,
                motivo_anulacion TEXT,
                FOREIGN KEY (renpre_sustancia_id)
                    REFERENCES renpre_sustancias(id),
                FOREIGN KEY (usuario_id)
                    REFERENCES usuarios(id)
            )
        """)

        # Migración compatible con instalaciones que ya tenían el módulo.
        asegurar_columnas(
            conn,
            "renpre_sustancias",
            {
                "fecha_stock_inicial": "TEXT",
            }
        )

        asegurar_columnas(
            conn,
            "renpre_movimientos",
            {
                "anulado": "INTEGER NOT NULL DEFAULT 0",
                "anulado_en": "TEXT",
                "anulado_por": "INTEGER",
                "motivo_anulacion": "TEXT",
            }
        )

        conn.execute("""
            UPDATE renpre_sustancias
            SET fecha_stock_inicial=?
            WHERE fecha_stock_inicial IS NULL
               OR TRIM(fecha_stock_inicial)=''
        """, (RENPRE_FECHA_STOCK_BASE,))

        # Vinculación automática por nombre normalizado.
        drogas = conn.execute("""
            SELECT rowid AS droga_rowid, nombre
            FROM drogas
        """).fetchall()

        mapa_drogas = {}
        for d in drogas:
            clave = normalizar_nombre_renpre(d["nombre"])
            mapa_drogas.setdefault(
                clave,
                d["droga_rowid"]
            )

        existentes = {
            normalizar_nombre_renpre(
                fila["nombre_renpre"]
            ): fila
            for fila in conn.execute(
                "SELECT * FROM renpre_sustancias"
            ).fetchall()
        }

        for nombre, stock, unidad in RENPRE_SUSTANCIAS_INICIALES:
            clave = normalizar_nombre_renpre(nombre)
            droga_rowid = mapa_drogas.get(clave)

            if clave not in existentes:
                conn.execute("""
                    INSERT INTO renpre_sustancias (
                        droga_rowid,
                        nombre_renpre,
                        activo,
                        stock_inicial,
                        unidad_stock,
                        fecha_stock_inicial
                    )
                    VALUES (?, ?, 1, ?, ?, ?)
                """, (
                    droga_rowid,
                    nombre,
                    stock,
                    unidad,
                    RENPRE_FECHA_STOCK_BASE
                ))

            elif droga_rowid and not existentes[clave]["droga_rowid"]:
                conn.execute("""
                    UPDATE renpre_sustancias
                    SET droga_rowid=?
                    WHERE id=?
                """, (
                    droga_rowid,
                    existentes[clave]["id"]
                ))

        conn.commit()


crear_tablas_renpre()


def signo_movimiento_renpre(sentido):
    return {
        "INGRESO": 1,
        "EGRESO": -1,
        "AJUSTE_POSITIVO": 1,
        "AJUSTE_NEGATIVO": -1,
    }.get(sentido, 0)


def obtener_sustancia_renpre(conn, renpre_sustancia_id):
    return conn.execute("""
        SELECT *
        FROM renpre_sustancias
        WHERE id=?
    """, (renpre_sustancia_id,)).fetchone()


def obtener_movimientos_renpre_ordenados(
    conn,
    renpre_sustancia_id,
    fecha_desde=None,
    fecha_hasta=None
):
    condiciones = [
        "renpre_sustancia_id=?",
        "COALESCE(anulado, 0)=0"
    ]
    parametros = [renpre_sustancia_id]

    if fecha_desde:
        condiciones.append("date(fecha) >= date(?)")
        parametros.append(fecha_desde)

    if fecha_hasta:
        condiciones.append("date(fecha) <= date(?)")
        parametros.append(fecha_hasta)

    sql = f"""
        SELECT *
        FROM renpre_movimientos
        WHERE {' AND '.join(condiciones)}
        ORDER BY date(fecha) ASC, id ASC
    """

    return conn.execute(
        sql,
        tuple(parametros)
    ).fetchall()


def simular_stock_renpre(
    conn,
    renpre_sustancia_id,
    movimiento_objetivo_id=None
):
    """
    Reconstruye el stock completo respetando fecha + id.
    Devuelve también el stock inmediatamente anterior/posterior
    al movimiento objetivo, cuando se proporciona su id.
    """
    sustancia = obtener_sustancia_renpre(
        conn,
        renpre_sustancia_id
    )

    if not sustancia:
        return {
            "ok": False,
            "error": "Sustancia RENPRE no encontrada."
        }

    fecha_base = (
        sustancia["fecha_stock_inicial"]
        or RENPRE_FECHA_STOCK_BASE
    )

    stock = float(
        sustancia["stock_inicial"]
        or 0
    )

    antes_objetivo = None
    despues_objetivo = None

    movimientos = conn.execute("""
        SELECT *
        FROM renpre_movimientos
        WHERE renpre_sustancia_id=?
          AND COALESCE(anulado, 0)=0
          AND date(fecha) >= date(?)
        ORDER BY date(fecha) ASC, id ASC
    """, (
        renpre_sustancia_id,
        fecha_base
    )).fetchall()

    for mov in movimientos:
        stock_antes = stock
        stock += (
            signo_movimiento_renpre(
                mov["sentido"]
            )
            * float(mov["cantidad"] or 0)
        )

        if mov["id"] == movimiento_objetivo_id:
            antes_objetivo = stock_antes
            despues_objetivo = stock

        if stock < -1e-9:
            return {
                "ok": False,
                "error": (
                    "La secuencia de movimientos deja "
                    "stock negativo el "
                    f"{mov['fecha']}."
                ),
                "stock_final": stock
            }

    # Evita residuos mínimos de punto flotante.
    if abs(stock) < 1e-9:
        stock = 0.0

    return {
        "ok": True,
        "stock_final": stock,
        "stock_antes_objetivo": antes_objetivo,
        "stock_despues_objetivo": despues_objetivo
    }


def calcular_stock_renpre(conn, renpre_sustancia_id):
    simulacion = simular_stock_renpre(
        conn,
        renpre_sustancia_id
    )

    if not simulacion.get("ok"):
        return 0.0

    return float(
        simulacion.get("stock_final", 0)
    )


def calcular_stock_apertura_renpre(
    conn,
    renpre_sustancia_id,
    fecha_inicio
):
    sustancia = obtener_sustancia_renpre(
        conn,
        renpre_sustancia_id
    )

    if not sustancia:
        raise ValueError(
            "Sustancia RENPRE no encontrada."
        )

    fecha_base = (
        sustancia["fecha_stock_inicial"]
        or RENPRE_FECHA_STOCK_BASE
    )

    if fecha_inicio < fecha_base:
        raise ValueError(
            "El período solicitado comienza antes del "
            f"stock base ({fecha_base})."
        )

    stock = float(
        sustancia["stock_inicial"]
        or 0
    )

    movimientos_previos = conn.execute("""
        SELECT sentido, cantidad
        FROM renpre_movimientos
        WHERE renpre_sustancia_id=?
          AND COALESCE(anulado, 0)=0
          AND date(fecha) >= date(?)
          AND date(fecha) < date(?)
        ORDER BY date(fecha) ASC, id ASC
    """, (
        renpre_sustancia_id,
        fecha_base,
        fecha_inicio
    )).fetchall()

    for mov in movimientos_previos:
        stock += (
            signo_movimiento_renpre(
                mov["sentido"]
            )
            * float(mov["cantidad"] or 0)
        )

        if stock < -1e-9:
            raise ValueError(
                "Hay una inconsistencia histórica: "
                "el stock queda negativo antes del período."
            )

    if abs(stock) < 1e-9:
        stock = 0.0

    return stock


def obtener_periodo_renpre(anio_texto, trimestre_texto):
    try:
        anio = int(anio_texto)
    except (TypeError, ValueError):
        raise ValueError("El año no es válido.")

    if anio < 2000 or anio > 2100:
        raise ValueError("El año no es válido.")

    trimestre = (trimestre_texto or "").strip().upper()

    if trimestre in ("", "ANUAL", "AÑO", "ANO", "0"):
        return {
            "anio": anio,
            "trimestre": None,
            "inicio": f"{anio:04d}-01-01",
            "fin": f"{anio:04d}-12-31",
            "etiqueta": f"Informe Anual - Año: {anio}",
            "archivo": f"RENPRE_LIBIM_ANUAL_{anio}"
        }

    if trimestre not in ("1", "2", "3", "4"):
        raise ValueError(
            "El trimestre debe ser 1, 2, 3, 4 o ANUAL."
        )

    limites = {
        "1": ("01-01", "03-31"),
        "2": ("04-01", "06-30"),
        "3": ("07-01", "09-30"),
        "4": ("10-01", "12-31"),
    }

    inicio_md, fin_md = limites[trimestre]

    return {
        "anio": anio,
        "trimestre": int(trimestre),
        "inicio": f"{anio:04d}-{inicio_md}",
        "fin": f"{anio:04d}-{fin_md}",
        "etiqueta": (
            f"Informe Trimestral: {trimestre} "
            f"- Año: {anio}"
        ),
        "archivo": f"RENPRE_LIBIM_T{trimestre}_{anio}"
    }


@app.route('/renpre')
@login_required
def renpre():
    with conectar_db() as conn:
        sustancias = conn.execute("""
            SELECT
                r.*,
                d.nombre AS nombre_inventario,
                d.numero AS numero_inventario
            FROM renpre_sustancias r
            LEFT JOIN drogas d
                ON d.rowid = r.droga_rowid
            ORDER BY r.nombre_renpre ASC
        """).fetchall()

        filas = []
        for s in sustancias:
            fila = dict(s)
            fila["stock_actual"] = calcular_stock_renpre(
                conn,
                s["id"]
            )
            filas.append(fila)

        movimientos = conn.execute("""
            SELECT
                m.*,
                r.nombre_renpre,
                u.usuario,
                ua.usuario AS usuario_anulacion
            FROM renpre_movimientos m
            JOIN renpre_sustancias r
                ON r.id = m.renpre_sustancia_id
            LEFT JOIN usuarios u
                ON u.id = m.usuario_id
            LEFT JOIN usuarios ua
                ON ua.id = m.anulado_por
            ORDER BY
                date(m.fecha) DESC,
                m.id DESC
            LIMIT 200
        """).fetchall()

    return render_template(
        'renpre.html',
        sustancias=filas,
        movimientos=movimientos,
        anio_actual=datetime.now().year
    )


@app.route('/renpre/configurar/<int:id>', methods=['POST'])
@roles_required("admin", "tecnico")
def renpre_configurar(id):
    activo = (
        1
        if request.form.get("activo") == "on"
        else 0
    )

    try:
        stock_inicial = float(
            str(
                request.form.get(
                    "stock_inicial",
                    "0"
                )
            ).replace(",", ".")
        )
    except ValueError:
        flash("El stock inicial debe ser numérico.")
        return redirect(url_for("renpre"))

    if stock_inicial < 0:
        flash("El stock inicial no puede ser negativo.")
        return redirect(url_for("renpre"))

    unidad_stock = request.form.get(
        "unidad_stock",
        ""
    ).strip()

    with conectar_db() as conn:
        sustancia = obtener_sustancia_renpre(
            conn,
            id
        )

        if not sustancia:
            flash("Sustancia RENPRE no encontrada.")
            return redirect(url_for("renpre"))

        fecha_stock_inicial = request.form.get(
            "fecha_stock_inicial",
            ""
        ).strip()

        if not fecha_stock_inicial:
            fecha_stock_inicial = (
                sustancia["fecha_stock_inicial"]
                or RENPRE_FECHA_STOCK_BASE
            )

        if not fecha_renpre_valida(fecha_stock_inicial):
            flash("La fecha del stock inicial no es válida.")
            return redirect(url_for("renpre"))

        cantidad_movimientos = conn.execute("""
            SELECT COUNT(*)
            FROM renpre_movimientos
            WHERE renpre_sustancia_id=?
              AND COALESCE(anulado, 0)=0
        """, (id,)).fetchone()[0]

        cambio_base = (
            abs(
                float(sustancia["stock_inicial"] or 0)
                - stock_inicial
            ) > 1e-9
            or normalizar_unidad_renpre(
                sustancia["unidad_stock"]
            ) != normalizar_unidad_renpre(
                unidad_stock
            )
            or (
                sustancia["fecha_stock_inicial"]
                or RENPRE_FECHA_STOCK_BASE
            ) != fecha_stock_inicial
        )

        if cantidad_movimientos and cambio_base:
            flash(
                "Esta sustancia ya tiene movimientos RENPRE. "
                "Para corregir el saldo usa un ajuste; no se "
                "puede modificar el stock base sin alterar la "
                "trazabilidad."
            )
            return redirect(url_for("renpre"))

        conn.execute("""
            UPDATE renpre_sustancias
            SET
                activo=?,
                stock_inicial=?,
                unidad_stock=?,
                fecha_stock_inicial=?
            WHERE id=?
        """, (
            activo,
            stock_inicial,
            unidad_stock,
            fecha_stock_inicial,
            id
        ))
        conn.commit()

    flash("Configuración RENPRE actualizada.")
    return redirect(url_for("renpre"))


@app.route('/renpre/movimiento', methods=['POST'])
@roles_required("admin", "tecnico")
def renpre_movimiento():
    renpre_sustancia_id = request.form.get(
        "renpre_sustancia_id",
        type=int
    )

    fecha = request.form.get(
        "fecha",
        ""
    ).strip()

    tipo_operacion = request.form.get(
        "tipo_operacion",
        ""
    ).strip()

    sentido = request.form.get(
        "sentido",
        ""
    ).strip()

    try:
        cantidad = float(
            str(
                request.form.get(
                    "cantidad",
                    "0"
                )
            ).replace(",", ".")
        )
    except ValueError:
        flash("La cantidad debe ser numérica.")
        return redirect(url_for("renpre"))

    unidad = request.form.get(
        "unidad",
        ""
    ).strip()

    documento_tipo = request.form.get(
        "documento_tipo",
        ""
    ).strip()

    documento_numero = request.form.get(
        "documento_numero",
        ""
    ).strip()

    transportista = request.form.get(
        "transportista",
        ""
    ).strip()

    remitente_destinatario = request.form.get(
        "remitente_destinatario",
        ""
    ).strip()

    titular_dni = request.form.get(
        "titular_dni",
        ""
    ).strip()

    observacion = request.form.get(
        "observacion",
        ""
    ).strip()

    if not renpre_sustancia_id:
        flash("Selecciona una sustancia RENPRE.")
        return redirect(url_for("renpre"))

    if not fecha_renpre_valida(fecha):
        flash("La fecha del movimiento no es válida.")
        return redirect(url_for("renpre"))

    if not tipo_operacion:
        flash("Completa el tipo de operación.")
        return redirect(url_for("renpre"))

    if sentido not in (
        "INGRESO",
        "EGRESO",
        "AJUSTE_POSITIVO",
        "AJUSTE_NEGATIVO"
    ):
        flash("Selecciona un sentido válido.")
        return redirect(url_for("renpre"))

    if cantidad <= 0:
        flash("La cantidad debe ser mayor que cero.")
        return redirect(url_for("renpre"))

    with conectar_db() as conn:
        sustancia = obtener_sustancia_renpre(
            conn,
            renpre_sustancia_id
        )

        if not sustancia:
            flash("Sustancia RENPRE no encontrada.")
            return redirect(url_for("renpre"))

        fecha_base = (
            sustancia["fecha_stock_inicial"]
            or RENPRE_FECHA_STOCK_BASE
        )

        if fecha < fecha_base:
            flash(
                "El movimiento no puede ser anterior al "
                f"stock base ({fecha_base})."
            )
            return redirect(url_for("renpre"))

        unidad_stock = (
            sustancia["unidad_stock"]
            or ""
        ).strip()

        if not unidad:
            unidad = unidad_stock

        # El saldo solo puede sumarse/restarse de forma segura cuando
        # la operación usa la misma unidad que el stock configurado.
        if (
            unidad_stock
            and unidad
            and normalizar_unidad_renpre(unidad_stock)
            != normalizar_unidad_renpre(unidad)
        ):
            flash(
                "La unidad del movimiento debe coincidir con "
                f"la unidad de stock ({unidad_stock})."
            )
            return redirect(url_for("renpre"))

        cursor = conn.execute("""
            INSERT INTO renpre_movimientos (
                renpre_sustancia_id,
                usuario_id,
                fecha,
                tipo_operacion,
                sentido,
                cantidad,
                unidad,
                documento_tipo,
                documento_numero,
                transportista,
                remitente_destinatario,
                titular_dni,
                observacion,
                creado_en,
                anulado
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            renpre_sustancia_id,
            session.get("usuario_id"),
            fecha,
            tipo_operacion,
            sentido,
            cantidad,
            unidad,
            documento_tipo,
            documento_numero,
            transportista,
            remitente_destinatario,
            titular_dni,
            observacion,
            fecha_actual()
        ))

        nuevo_id = cursor.lastrowid

        simulacion = simular_stock_renpre(
            conn,
            renpre_sustancia_id,
            movimiento_objetivo_id=nuevo_id
        )

        if not simulacion.get("ok"):
            conn.rollback()
            flash(
                simulacion.get(
                    "error",
                    "El movimiento genera un stock inválido."
                )
            )
            return redirect(url_for("renpre"))

        stock_antes = simulacion.get(
            "stock_antes_objetivo"
        )
        stock_despues = simulacion.get(
            "stock_despues_objetivo"
        )

        # También deja traza en el historial general si está vinculada
        # a una sustancia del inventario.
        if sustancia["droga_rowid"]:
            registrar_movimiento(
                conn,
                sustancia["droga_rowid"],
                f"RENPRE - {tipo_operacion}",
                f"{cantidad:g} {unidad}".strip(),
                (
                    f"{sentido}. Stock RENPRE: "
                    f"{stock_antes:g} → {stock_despues:g}. "
                    f"{observacion}"
                ).strip()
            )

        conn.commit()

    flash("Movimiento RENPRE registrado correctamente.")
    return redirect(url_for("renpre"))


@app.route(
    '/renpre/movimiento/<int:id>/eliminar',
    methods=['POST']
)
@roles_required("admin")
def renpre_eliminar_movimiento(id):
    motivo = request.form.get(
        "motivo_anulacion",
        ""
    ).strip()

    with conectar_db() as conn:
        movimiento = conn.execute("""
            SELECT
                m.*,
                r.droga_rowid,
                r.nombre_renpre
            FROM renpre_movimientos m
            JOIN renpre_sustancias r
                ON r.id = m.renpre_sustancia_id
            WHERE m.id=?
        """, (id,)).fetchone()

        if not movimiento:
            flash("Movimiento RENPRE no encontrado.")
            return redirect(url_for("renpre"))

        if movimiento["anulado"]:
            flash("Ese movimiento ya se encuentra anulado.")
            return redirect(url_for("renpre"))

        # No se borra: se conserva la trazabilidad.
        conn.execute("""
            UPDATE renpre_movimientos
            SET
                anulado=1,
                anulado_en=?,
                anulado_por=?,
                motivo_anulacion=?
            WHERE id=?
        """, (
            fecha_actual(),
            session.get("usuario_id"),
            motivo,
            id
        ))

        simulacion = simular_stock_renpre(
            conn,
            movimiento["renpre_sustancia_id"]
        )

        if not simulacion.get("ok"):
            conn.rollback()
            flash(
                "No se puede anular ese movimiento porque "
                "dejaría un stock histórico negativo. "
                "Revisa primero los movimientos posteriores."
            )
            return redirect(url_for("renpre"))

        if movimiento["droga_rowid"]:
            registrar_movimiento(
                conn,
                movimiento["droga_rowid"],
                "RENPRE - movimiento anulado",
                (
                    f"{movimiento['cantidad']:g} "
                    f"{movimiento['unidad'] or ''}"
                ).strip(),
                (
                    f"Se anuló el movimiento RENPRE #{id} "
                    f"({movimiento['tipo_operacion']}, "
                    f"{movimiento['fecha']}). "
                    f"Motivo: {motivo or 'Sin especificar'}"
                )
            )

        conn.commit()

    flash(
        "Movimiento RENPRE anulado. "
        "La trazabilidad fue conservada."
    )
    return redirect(url_for("renpre"))


def copiar_estilo_fila_renpre(
    ws,
    fila_origen,
    fila_destino,
    max_col=14
):
    """Copia el formato de una fila de la plantilla oficial."""
    ws.row_dimensions[fila_destino].height = (
        ws.row_dimensions[fila_origen].height
    )

    for col in range(1, max_col + 1):
        origen = ws.cell(
            row=fila_origen,
            column=col
        )
        destino = ws.cell(
            row=fila_destino,
            column=col
        )

        if origen.has_style:
            destino._style = copy(origen._style)

        if origen.number_format:
            destino.number_format = origen.number_format

        if origen.alignment:
            destino.alignment = copy(origen.alignment)

        if origen.protection:
            destino.protection = copy(origen.protection)


def preparar_filas_plantilla_renpre(
    ws,
    cantidad_filas
):
    fila_inicio = 13
    fila_modelo = 36 if ws.max_row >= 36 else fila_inicio
    filas_disponibles = max(
        0,
        ws.max_row - fila_inicio + 1
    )

    if cantidad_filas > filas_disponibles:
        extras = cantidad_filas - filas_disponibles
        insertar_en = ws.max_row + 1
        ws.insert_rows(
            insertar_en,
            amount=extras
        )

        for fila in range(
            insertar_en,
            insertar_en + extras
        ):
            copiar_estilo_fila_renpre(
                ws,
                fila_modelo,
                fila
            )

    # Limpia valores antiguos sin destruir el formato oficial.
    ultima_fila = max(
        ws.max_row,
        fila_inicio + cantidad_filas - 1
    )

    for fila in range(
        fila_inicio,
        ultima_fila + 1
    ):
        for col in range(1, 15):
            ws.cell(
                row=fila,
                column=col
            ).value = None

    return fila_inicio


@app.route('/renpre/exportar')
@login_required
def renpre_exportar():
    trimestre = request.args.get(
        "trimestre",
        ""
    ).strip()

    anio = request.args.get(
        "anio",
        str(datetime.now().year)
    ).strip()

    try:
        periodo = obtener_periodo_renpre(
            anio,
            trimestre
        )
    except ValueError as e:
        flash(str(e))
        return redirect(url_for("renpre"))

    if periodo["inicio"] < RENPRE_FECHA_STOCK_BASE:
        flash(
            "No se puede generar un informe anterior a "
            f"{RENPRE_FECHA_STOCK_BASE}, porque ese es el "
            "stock base disponible en el sistema."
        )
        return redirect(url_for("renpre"))

    if not os.path.exists(RENPRE_PLANTILLA):
        flash(
            "No se encontró la plantilla RENPRE. "
            "Debes incluir RENPRE_LIBIM_PLANTILLA.xlsx "
            "junto a app.py."
        )
        return redirect(url_for("renpre"))

    with conectar_db() as conn:
        # Se incluyen las sustancias activas y también cualquier sustancia
        # que tenga movimientos en el período, aunque luego haya sido
        # desactivada.
        sustancias = conn.execute("""
            SELECT r.*
            FROM renpre_sustancias r
            WHERE r.activo=1
               OR EXISTS (
                    SELECT 1
                    FROM renpre_movimientos m
                    WHERE m.renpre_sustancia_id=r.id
                      AND COALESCE(m.anulado, 0)=0
                      AND date(m.fecha) BETWEEN date(?) AND date(?)
               )
            ORDER BY r.nombre_renpre ASC
        """, (
            periodo["inicio"],
            periodo["fin"]
        )).fetchall()

        datos = []

        for s in sustancias:
            try:
                stock = calcular_stock_apertura_renpre(
                    conn,
                    s["id"],
                    periodo["inicio"]
                )
            except ValueError as e:
                flash(
                    f"{s['nombre_renpre']}: {e}"
                )
                return redirect(url_for("renpre"))

            movimientos = obtener_movimientos_renpre_ordenados(
                conn,
                s["id"],
                fecha_desde=periodo["inicio"],
                fecha_hasta=periodo["fin"]
            )

            unidad_stock = (
                s["unidad_stock"]
                or ""
            )

            if not movimientos:
                datos.append({
                    "fecha": None,
                    "nombre": s["nombre_renpre"],
                    "stock_inicial": stock,
                    "unidad_inicial": unidad_stock,
                    "tipo": "",
                    "cantidad": None,
                    "unidad_operacion": "",
                    "stock_final": stock,
                    "unidad_final": unidad_stock,
                    "documento_tipo": "",
                    "documento_numero": "",
                    "transportista": "",
                    "remitente_destinatario": "",
                    "titular_dni": ""
                })
                continue

            for mov in movimientos:
                stock_antes = stock
                stock += (
                    signo_movimiento_renpre(
                        mov["sentido"]
                    )
                    * float(mov["cantidad"] or 0)
                )

                if stock < -1e-9:
                    flash(
                        "No se puede exportar: "
                        f"{s['nombre_renpre']} queda con "
                        f"stock negativo el {mov['fecha']}."
                    )
                    return redirect(url_for("renpre"))

                fecha_excel = None
                if mov["fecha"]:
                    fecha_excel = datetime.strptime(
                        mov["fecha"],
                        "%Y-%m-%d"
                    )

                datos.append({
                    "fecha": fecha_excel,
                    "nombre": s["nombre_renpre"],
                    "stock_inicial": stock_antes,
                    "unidad_inicial": unidad_stock,
                    "tipo": mov["tipo_operacion"],
                    "cantidad": float(mov["cantidad"]),
                    "unidad_operacion": (
                        mov["unidad"]
                        or unidad_stock
                    ),
                    "stock_final": stock,
                    "unidad_final": unidad_stock,
                    "documento_tipo": (
                        mov["documento_tipo"]
                        or ""
                    ),
                    "documento_numero": (
                        mov["documento_numero"]
                        or ""
                    ),
                    "transportista": (
                        mov["transportista"]
                        or ""
                    ),
                    "remitente_destinatario": (
                        mov["remitente_destinatario"]
                        or ""
                    ),
                    "titular_dni": (
                        mov["titular_dni"]
                        or ""
                    )
                })

    # Se parte del archivo oficial para conservar diseño, merges,
    # impresión y encabezados. No se reconstruye una copia aproximada.
    wb = load_workbook(RENPRE_PLANTILLA)

    if "Planilla tipo general" in wb.sheetnames:
        ws = wb["Planilla tipo general"]
    else:
        ws = wb.active

    ws["A5"] = periodo["etiqueta"]

    fila = preparar_filas_plantilla_renpre(
        ws,
        len(datos)
    )

    for d in datos:
        ws.cell(
            row=fila,
            column=1,
            value=d["fecha"]
        )
        if d["fecha"]:
            ws.cell(
                row=fila,
                column=1
            ).number_format = "dd/mm/yyyy"

        ws.cell(
            row=fila,
            column=2,
            value=d["nombre"]
        )
        ws.cell(
            row=fila,
            column=3,
            value=d["stock_inicial"]
        )
        ws.cell(
            row=fila,
            column=4,
            value=d["unidad_inicial"]
        )
        ws.cell(
            row=fila,
            column=5,
            value=d["tipo"]
        )
        ws.cell(
            row=fila,
            column=6,
            value=d["cantidad"]
        )
        ws.cell(
            row=fila,
            column=7,
            value=d["unidad_operacion"]
        )
        ws.cell(
            row=fila,
            column=8,
            value=d["stock_final"]
        )
        ws.cell(
            row=fila,
            column=9,
            value=d["unidad_final"]
        )
        ws.cell(
            row=fila,
            column=10,
            value=d["documento_tipo"]
        )
        ws.cell(
            row=fila,
            column=11,
            value=d["documento_numero"]
        )
        ws.cell(
            row=fila,
            column=12,
            value=d["transportista"]
        )
        ws.cell(
            row=fila,
            column=13,
            value=d["remitente_destinatario"]
        )
        ws.cell(
            row=fila,
            column=14,
            value=d["titular_dni"]
        )

        fila += 1

    ultima_fila_datos = max(
        13,
        12 + len(datos)
    )

    # Si la plantilla tenía más filas formateadas, no altera el diseño;
    # el área de impresión sí se limita al contenido útil.
    ws.print_area = f"A1:N{ultima_fila_datos}"

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        download_name=(
            f"{periodo['archivo']}.xlsx"
        ),
        as_attachment=True,
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    )


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True)