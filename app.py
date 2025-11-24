from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
import sqlite3
import pandas as pd
import os
import base64
import requests

app = Flask(__name__)
app.secret_key = "clave_secreta"

# --- Configurar tu clave de Google Vision ---
API_KEY = os.getenv("GOOGLE_API_KEY") or "TU_API_KEY_AQUI"  # reemplazá por tu clave si querés probar directo

# --- Conexión a la base de datos ---
def conectar_db():
    ruta_db = os.path.join(os.path.dirname(__file__), "sustancias.db")
    conn = sqlite3.connect(ruta_db)
    conn.row_factory = sqlite3.Row
    return conn

# --- Crear tabla si no existe ---
def crear_tabla():
    with conectar_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS drogas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero INTEGER,
                nombre TEXT NOT NULL,
                peligros TEXT,
                cancerigeno TEXT,
                cantidad TEXT,
                ubicacion TEXT
            )
        ''')
crear_tabla()

# --- Página principal: muestra la biblioteca de sustancias ---
@app.route('/')
def index():
    busqueda = request.args.get('busqueda', '').strip()

    with conectar_db() as conn:
        if busqueda:
            cursor = conn.execute("""
                SELECT * FROM drogas 
                WHERE nombre LIKE ? OR peligros LIKE ? OR ubicacion LIKE ? OR cantidad LIKE ?
                ORDER BY nombre ASC
            """, (f'%{busqueda}%', f'%{busqueda}%', f'%{busqueda}%', f'%{busqueda}%'))
        else:
            cursor = conn.execute("SELECT * FROM drogas ORDER BY nombre ASC")
        drogas = cursor.fetchall()

    return render_template('index.html', drogas=drogas, busqueda=busqueda)

# --- Agregar nueva sustancia ---
@app.route('/agregar', methods=['GET', 'POST'])
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

        flash("✅ Sustancia agregada correctamente.")
        return redirect(url_for('index'))

    return render_template('agregar.html')

# --- Editar sustancia ---
@app.route('/editar/<int:id>', methods=['GET', 'POST'])
def editar(id):
    with conectar_db() as conn:
        cursor = conn.execute("SELECT * FROM drogas WHERE id=?", (id,))
        droga = cursor.fetchone()

        if not droga:
            flash("⚠️ Sustancia no encontrada.")
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
            flash("💾 Cambios guardados correctamente.")
            return redirect(url_for('index'))

    return render_template('editar.html', droga=droga)

# --- Eliminar sustancia ---
@app.route('/eliminar/<int:id>')
def eliminar(id):
    with conectar_db() as conn:
        conn.execute("DELETE FROM drogas WHERE id=?", (id,))
        conn.commit()
    flash("🗑️ Sustancia eliminada correctamente.")
    return redirect(url_for('index'))

# --- Exportar a Excel ---
@app.route('/exportar_excel')
def exportar_excel():
    with conectar_db() as conn:
        df = pd.read_sql_query("SELECT * FROM drogas", conn)
    ruta_excel = "sustancias_exportadas.xlsx"
    df.to_excel(ruta_excel, index=False)
    return send_file(ruta_excel, as_attachment=True)

# --- Detección de texto en imágenes usando Google Vision ---
@app.route('/detectar_texto', methods=['POST'])
def detectar_texto():
    if 'image' not in request.files:
        return jsonify({'error': 'No se subió ninguna imagen'}), 400

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
        texto = "No se detectó texto."

    flash(f"🧠 Texto detectado: {texto}")
    return redirect(url_for('index'))

# --- Iniciar app ---
if __name__ == '__main__':
    app.run(debug=True)
