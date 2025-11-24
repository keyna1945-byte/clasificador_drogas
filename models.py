from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Droga(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.Integer)
    nombre = db.Column(db.String(100))
    peligros = db.Column(db.String(200))
    cancerigeno = db.Column(db.String(50))
    cantidad = db.Column(db.String(50))       
    ubicacion = db.Column(db.String(100))      
