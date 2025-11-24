import sqlite3

conn = sqlite3.connect('instance/drogas.db')
cursor = conn.cursor()

cursor.execute("SELECT numero, nombre FROM drogas WHERE numero BETWEEN 1000 AND 1550")
rows = cursor.fetchall()

if rows:
    print(f"✅ Se encontraron {len(rows)} sustancias entre 1000 y 1550:")
    for row in rows:
        print(row)
else:
    print("❌ No se encontraron drogas en ese rango.")

conn.close()
