from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime

# Configurar la base de datos SQLite
DATABASE_URL = "sqlite:///./database.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Dispositivo(Base):
    __tablename__ = "dispositivos"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    ip = Column(String, nullable=False)
    hostname = Column(String, nullable=True)  # ← NUEVO CAMPO
    tipo = Column(String, nullable=False)
    tienda = Column(String, nullable=False)

class Historial(Base):
    __tablename__ = "historial"
    id = Column(Integer, primary_key=True, index=True)
    dispositivo = Column(String, nullable=False)
    estado = Column(String, nullable=False)
    fecha = Column(DateTime, default=datetime.datetime.now)

# Crear las tablas
Base.metadata.create_all(bind=engine)