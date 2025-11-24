import sqlite3
import pandas as pd

# Leer el Excel
df = pd.read_excel("datos.xlsx")

# Mostrar columnas para confirmar
print("Columnas encontradas en el Excel:")
print(df.columns)

# Conexión a la base de datos
conn = sqlite3.connect("sustancias.db")

# Insertar los datos en la tabla drogas
df.to_sql("drogas", conn, if_exists="replace", index=False)

conn.close()
print("✅ Datos importados correctamente a la base de datos.")
