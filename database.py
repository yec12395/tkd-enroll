import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# 自動辨識環境變數，若無則預設使用本地 SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///competition.db")

# 針對 SQLite 進行多執行緒優化配置
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()