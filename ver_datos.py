import sqlite3

conn = sqlite3.connect('instance/drogas.db')
cur = conn.cursor()

try:
    cur.execute("SELECT * FROM droga;")
    filas = cur.fetchall()

    if filas:
        print("\n✅ Registros encontrados en la tabla 'droga':\n")
        for fila in filas:
            print(fila)
    else:
        print("\n⚠️ La tabla 'droga' está vacía (no hay registros aún).")

except Exception as e:
    print("❌ Error al leer la tabla 'droga':", e)

conn.close()
