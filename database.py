import os
from pathlib import Path
from tempfile import gettempdir

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


def default_sqlite_url() -> str:
    db_path = Path(__file__).resolve().with_name("competition.db")
    if str(db_path).startswith("/mount/src/"):
        data_dir = Path(os.getenv("SQLITE_DATA_DIR", Path(gettempdir()) / "tkd-enroll"))
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = data_dir / "competition.db"
    return f"sqlite:///{db_path.as_posix()}"


# 自動辨識環境變數，若無則預設使用本地 SQLite
DATABASE_URL = os.getenv("DATABASE_URL", default_sqlite_url())

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
