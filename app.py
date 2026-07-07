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

# --- Configurar tu clave de Google Vision ---
API_KEY = os.getenv("GOOGLE_API_KEY") or "TU_API_KEY_AQUI"
ROLES = ("admin", "tecnico", "consulta")


def fecha_actual():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --- Conexion a la base de datos ---
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
            INSERT INTO login_logs (usuario_id, usuario, fecha, ip, exitoso, detalle)
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


# --- Crear tablas si no existen ---
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
                FOREIGN KEY (droga_id) REFERENCES drogas(id),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
        """)

        cantidad_usuarios = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        if cantidad_usuarios == 0:
            conn.execute("""
                INSERT INTO usuarios (usuario, password_hash, rol, activo, creado_en)
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


# --- Autenticacion ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form.get('usuario', '').strip()
        password = request.form.get('password', '')

        with conectar_db() as conn:
            cuenta = conn.execute("SELECT * FROM usuarios WHERE usuario=?", (usuario,)).fetchone()

        if not cuenta:
            registrar_inicio_sesion(None, usuario, False, "Usuario inexistente")
            flash("Usuario o contrasena incorrectos.")
            return redirect(url_for('login'))

        if not cuenta['activo']:
            registrar_inicio_sesion(cuenta['id'], usuario, False, "Usuario pendiente o inactivo")
            flash("Tu usuario todavia no esta activo. Consultale al administrador.")
            return redirect(url_for('login'))

        if not check_password_hash(cuenta['password_hash'], password):
            registrar_inicio_sesion(cuenta['id'], usuario, False, "Contrasena incorrecta")
            flash("Usuario o contrasena incorrectos.")
            return redirect(url_for('login'))

        session.clear()
        session['usuario_id'] = cuenta['id']
        session['usuario'] = cuenta['usuario']
        session['rol'] = cuenta['rol']
        registrar_inicio_sesion(cuenta['id'], usuario, True, "Inicio correcto")
        return redirect(request.args.get('siguiente') or url_for('index'))

    return render_template('login.html')


@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        usuario = request.form.get('usuario', '').strip()
        password = request.form.get('password', '')

        if not usuario or not password:
            flash("Completa usuario y contrasena.")
            return redirect(url_for('registro'))

        try:
            with conectar_db() as conn:
                conn.execute("""
                    INSERT INTO usuarios (usuario, password_hash, rol, activo, creado_en)
                    VALUES (?, ?, 'consulta', 0, ?)
                """, (usuario, generate_password_hash(password), fecha_actual()))
                conn.commit()
        except sqlite3.IntegrityError:
            flash("Ese usuario ya existe.")
            return redirect(url_for('registro'))

        flash("Usuario creado. Un administrador debe activarlo y asignar el rol.")
        return redirect(url_for('login'))

    return render_template('registro.html')


@app.route('/logout')
def logout():
    session.clear()
    flash("Sesion cerrada.")
    return redirect(url_for('login'))


# --- Pagina principal ---
@app.route('/')
@login_required
def index():
    busqueda = request.args.get('busqueda', '').strip()

    with conectar_db() as conn:
        if busqueda:
            cursor = conn.execute("""
                SELECT * FROM drogas
                WHERE CAST(numero AS TEXT) LIKE ?
                   OR nombre LIKE ?
                   OR peligros LIKE ?
                   OR ubicacion LIKE ?
                   OR cantidad LIKE ?
                ORDER BY nombre ASC
            """, (f'%{busqueda}%', f'%{busqueda}%', f'%{busqueda}%', f'%{busqueda}%', f'%{busqueda}%'))
        else:
            cursor = conn.execute("SELECT * FROM drogas ORDER BY nombre ASC")

        drogas = cursor.fetchall()

    return render_template('index.html', drogas=drogas, busqueda=busqueda)


# --- Ficha desde QR ---
@app.route('/sustancia/<int:numero>', methods=['GET', 'POST'])
@login_required
def ficha_sustancia(numero):
    with conectar_db() as conn:
        cursor = conn.execute("SELECT * FROM drogas WHERE numero=?", (numero,))
        droga = cursor.fetchone()

        if not droga:
            flash("Sustancia no encontrada.")
            return redirect(url_for('index'))

        if request.method == 'POST':
            if session.get("rol") not in ("admin", "tecnico"):
                flash("No tenes permiso para modificar movimientos o cantidades.")
                return redirect(url_for('ficha_sustancia', numero=numero))

            tipo = request.form.get('tipo')
            if tipo == 'cantidad':
                cantidad = request.form.get('cantidad', '').strip()
                conn.execute("UPDATE drogas SET cantidad=? WHERE id=?", (cantidad, droga['id']))
                conn.execute("""
                    INSERT INTO movimientos (droga_id, usuario_id, accion, cantidad, observacion, fecha)
                    VALUES (?, ?, 'actualizo cantidad', ?, ?, ?)
                """, (droga['id'], session.get('usuario_id'), cantidad, "Cambio manual de stock", fecha_actual()))
                conn.commit()
                flash("Cantidad actualizada correctamente.")
                return redirect(url_for('ficha_sustancia', numero=numero))

            accion = request.form.get('accion')
            cantidad_movimiento = request.form.get('cantidad_movimiento', '').strip()
            observacion = request.form.get('observacion', '').strip()
            if accion not in ("retirado", "en uso", "devuelto"):
                flash("Selecciona una accion valida.")
                return redirect(url_for('ficha_sustancia', numero=numero))

            conn.execute("""
                INSERT INTO movimientos (droga_id, usuario_id, accion, cantidad, observacion, fecha)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (droga['id'], session.get('usuario_id'), accion, cantidad_movimiento, observacion, fecha_actual()))
            conn.commit()
            flash("Movimiento registrado correctamente.")
            return redirect(url_for('ficha_sustancia', numero=numero))

        movimientos = conn.execute("""
            SELECT m.*, u.usuario
            FROM movimientos m
            LEFT JOIN usuarios u ON u.id = m.usuario_id
            WHERE m.droga_id=?
            ORDER BY m.fecha DESC, m.id DESC
            LIMIT 25
        """, (droga['id'],)).fetchall()

    return render_template('sustancia.html', droga=droga, movimientos=movimientos)


# --- Administracion de usuarios ---
@app.route('/usuarios', methods=['GET', 'POST'])
@roles_required("admin")
def usuarios():
    if request.method == 'POST':
        usuario = request.form.get('usuario', '').strip()
        password = request.form.get('password', '')
        rol = request.form.get('rol', 'consulta')
        activo = 1 if request.form.get('activo') == 'on' else 0

        if rol not in ROLES:
            rol = 'consulta'

        try:
            with conectar_db() as conn:
                conn.execute("""
                    INSERT INTO usuarios (usuario, password_hash, rol, activo, creado_en)
                    VALUES (?, ?, ?, ?, ?)
                """, (usuario, generate_password_hash(password), rol, activo, fecha_actual()))
                conn.commit()
            flash("Usuario creado correctamente.")
        except sqlite3.IntegrityError:
            flash("Ese usuario ya existe.")

        return redirect(url_for('usuarios'))

    with conectar_db() as conn:
        lista_usuarios = conn.execute("SELECT * FROM usuarios ORDER BY usuario ASC").fetchall()

    return render_template('usuarios.html', usuarios=lista_usuarios, roles=ROLES)


@app.route('/usuarios/<int:id>/actualizar', methods=['POST'])
@roles_required("admin")
def actualizar_usuario(id):
    rol = request.form.get('rol', 'consulta')
    activo = 1 if request.form.get('activo') == 'on' else 0
    nueva_password = request.form.get('password', '')

    if rol not in ROLES:
        rol = 'consulta'

    with conectar_db() as conn:
        if nueva_password:
            conn.execute("""
                UPDATE usuarios SET rol=?, activo=?, password_hash=? WHERE id=?
            """, (rol, activo, generate_password_hash(nueva_password), id))
        else:
            conn.execute("UPDATE usuarios SET rol=?, activo=? WHERE id=?", (rol, activo, id))
        conn.commit()

    flash("Usuario actualizado.")
    return redirect(url_for('usuarios'))


@app.route('/historial')
@roles_required("admin")
def historial():
    with conectar_db() as conn:
        logs = conn.execute("""
            SELECT * FROM login_logs
            ORDER BY fecha DESC, id DESC
            LIMIT 200
        """).fetchall()
        movimientos = conn.execute("""
            SELECT m.*, d.numero, d.nombre, u.usuario
            FROM movimientos m
            JOIN drogas d ON d.id = m.droga_id
            LEFT JOIN usuarios u ON u.id = m.usuario_id
            ORDER BY m.fecha DESC, m.id DESC
            LIMIT 200
        """).fetchall()

    return render_template('historial.html', logs=logs, movimientos=movimientos)


# --- Agregar ---
@app.route('/agregar', methods=['GET', 'POST'])
@roles_required("admin", "tecnico")
def agregar():
    if request.method == 'POST':
        numero = request.form['numero']
        nombre = request.form['nombre']
        peligros = request.form['peligros']
        cancerigeno = request.form['cancerigeno']
        cantidad = request.form['cantidad']
        ubicacion = request.form['ubicacion']

        with conectar_db() as conn:
            conn.execute("""
                INSERT INTO drogas (numero, nombre, peligros, cancerigeno, cantidad, ubicacion)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (numero, nombre, peligros, cancerigeno, cantidad, ubicacion))
            conn.commit()

        flash("Sustancia agregada correctamente.")
        return redirect(url_for('index'))

    return render_template('agregar.html')


# --- Editar ---
@app.route('/editar/<int:id>', methods=['GET', 'POST'])
@roles_required("admin", "tecnico")
def editar(id):
    with conectar_db() as conn:
        cursor = conn.execute("SELECT * FROM drogas WHERE id=?", (id,))
        droga = cursor.fetchone()

        if not droga:
            flash("Sustancia no encontrada.")
            return redirect(url_for('index'))

        if request.method == 'POST':
            ubicacion = request.form['ubicacion']
            nombre = request.form['nombre']
            numero = request.form['numero']
            cantidad = request.form['cantidad']
            peligros = request.form['peligros']
            cancerigeno = request.form['cancerigeno']

            conn.execute("""
                UPDATE drogas
                SET ubicacion=?, nombre=?, numero=?, cantidad=?, peligros=?, cancerigeno=?
                WHERE id=?
            """, (ubicacion, nombre, numero, cantidad, peligros, cancerigeno, id))
            conn.commit()

            flash("Cambios guardados correctamente.")
            return redirect(url_for('index'))

    return render_template('editar.html', droga=droga)


# --- Eliminar ---
@app.route('/eliminar/<int:id>')
@roles_required("admin")
def eliminar(id):
    with conectar_db() as conn:
        conn.execute("DELETE FROM drogas WHERE id=?", (id,))
        conn.commit()

    flash("Sustancia eliminada correctamente.")
    return redirect(url_for('index'))


# --- Exportar Excel ---
@app.route('/exportar_excel')
@login_required
def exportar_excel():
    with conectar_db() as conn:
        df = pd.read_sql_query("SELECT * FROM drogas", conn)

    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)

    return send_file(
        output,
        download_name="sustancias_exportadas.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# --- Deteccion de texto ---
@app.route('/detectar_texto', methods=['POST'])
@login_required
def detectar_texto():
    if 'image' not in request.files:
        return jsonify({'error': 'No se subio ninguna imagen'}), 400

    imagen = request.files['image']
    contenido = base64.b64encode(imagen.read()).decode()

    url = f"https://vision.googleapis.com/v1/images:annotate?key={API_KEY}"

    data = {
        "requests": [
            {
                "image": {"content": contenido},
                "features": [{"type": "TEXT_DETECTION"}]
            }
        ]
    }

    response = requests.post(url, json=data)
    resultado = response.json()

    try:
        texto = resultado['responses'][0]['textAnnotations'][0]['description']
    except (KeyError, IndexError):
        texto = "No se detecto texto."

    flash(f"Texto detectado: {texto}")
    return redirect(url_for('index'))


# --- Run ---
if __name__ == '__main__':
    app.run(debug=True)
