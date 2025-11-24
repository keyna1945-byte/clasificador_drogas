import sqlite3

# Conectar a la base de datos
conn = sqlite3.connect('instance/drogas.db')
cur = conn.cursor()

# Ver tablas
cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
print("Tablas en la base de datos:", cur.fetchall())

# Ver columnas de la tabla droga
try:
    cur.execute("PRAGMA table_info(droga);")
    print("\nColumnas en la tabla 'droga':")
    for col in cur.fetchall():
        print(col)
except Exception as e:
    print("\nError al consultar la tabla 'droga':", e)

conn.close()
