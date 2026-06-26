from backend.db.session import SessionLocal
from backend.db.models import Job
from sqlalchemy import select

db = SessionLocal()
for jid in ['d63e47adff51493583aa1921386f0fc2', '9561ff92474e4b41a4ae22d61cf96e82']:
    job = db.execute(select(Job).where(Job.id == jid)).scalar_one_or_none()
    if job:
        job.status = 'failed'
        job.error_log = 'cancelled by test'
        db.commit()
        print(jid, 'marked failed')
