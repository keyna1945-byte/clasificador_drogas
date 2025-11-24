import sqlite3
import os

# Ruta a tu base de datos
DB_PATH = 'instance/drogas.db'

# Ruta relativa a la imagen del estante
RUTA_IMAGEN = 'estantes/estante_1.jpg'

# Rango de números
NUM_MIN = 1000
NUM_MAX = 1550

# Conectar
if not os.path.exists(DB_PATH):
    print(f"❌ La base de datos no se encontró en {DB_PATH}")
    exit()

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Intentar agregar columna si no existe
try:
    cursor.execute("ALTER TABLE droga ADD COLUMN ruta_foto TEXT")
    print("✅ Columna 'ruta_foto' agregada.")
except sqlite3.OperationalError:
    print("ℹ️ La columna 'ruta_foto' ya existe.")

# Actualizar las filas
cursor.execute("""
    UPDATE droga
    SET ruta_foto = ?
    WHERE numero BETWEEN ? AND ?
""", (RUTA_IMAGEN, NUM_MIN, NUM_MAX))

# Mostrar cuántas filas se modificaron
filas_afectadas = cursor.rowcount
print(f"🔧 Se actualizaron {filas_afectadas} filas.")

conn.commit()
conn.close()

