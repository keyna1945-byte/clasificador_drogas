import sqlite3

conn = sqlite3.connect('instance/drogas.db')
cursor = conn.cursor()

cursor.execute("SELECT numero, ruta_foto FROM drogas WHERE numero BETWEEN 1000 AND 1550")
rows = cursor.fetchall()

for row in rows:
    print(row)

conn.close()
