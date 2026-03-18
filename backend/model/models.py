from sqlalchemy import Boolean, Column, Integer, String, ForeignKey, Float, Text
from database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    
class StructuralElement(Base):
    __tablename__ = "structural_elements"

    id = Column(Integer, primary_key=True)
    tmarka_elementa = Column(String)
    tclass_betona = Column(String)
    tthickness = Column(Integer)
    tbeton_m3 = Column(Float)
    tstal_kg = Column(Float)
    tcoef_a = Column(Float)
    
class ProcessedData(Base):
    __tablename__ = "processed_data"

    id = Column(Integer, primary_key=True, index=True)
    db_id = Column(Integer)
    punkt = Column(String)
    thickness = Column(Text)
    marka = Column(String)
    beton = Column(Float)
    stal = Column(Float)
    coef = Column(Float)