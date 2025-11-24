import sqlite3
import os

DB_PATH = "instance/drogas.db"

if not os.path.exists(DB_PATH):
    print("❌ No se encontró la base de datos en: ", DB_PATH)
    exit()

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# MOSTRAR TODAS LAS TABLAS
print("\n📋 Tablas en la base de datos:")
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tablas = cursor.fetchall()
for t in tablas:
    print(" -", t[0])

# MOSTRAR PRIMERAS FILAS DE CADA TABLA
for tabla in tablas:
    print(f"\n🔍 Primeras filas de la tabla: {tabla[0]}")
    try:
        cursor.execute(f"SELECT * FROM {tabla[0]} LIMIT 5;")
        filas = cursor.fetchall()
        for fila in filas:
            print(fila)
    except Exception as e:
        print("⚠️ Error al leer la tabla:", e)

conn.close()
