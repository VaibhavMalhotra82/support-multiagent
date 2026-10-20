from typing import List, Optional

from sqlalchemy.orm import Session

from app import db, observability


def create_rca_record(db_session: Session, symptom: str, root_cause: str, resolution: str, product: Optional[str] = None, version: Optional[str] = None, tags: Optional[List[str]] = None, tenant_id: Optional[str] = None) -> db.RootCauseAnalysis:
    record = db.RootCauseAnalysis(
        symptom=symptom,
        root_cause=root_cause,
        resolution=resolution,
        product=product,
        version=version,
        tags=','.join(tags) if tags else None,
        tenant_id=tenant_id,
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    observability.log_step("rca.create", "rca_record_created")
    return record


def search_rca(db_session: Session, symptom: str, tenant_id: Optional[str] = None) -> List[db.RootCauseAnalysis]:
    query = db_session.query(db.RootCauseAnalysis).filter(db.RootCauseAnalysis.symptom.ilike(f"%{symptom}%"))
    if tenant_id:
        query = query.filter(db.RootCauseAnalysis.tenant_id == tenant_id)
    results = query.order_by(db.RootCauseAnalysis.created_at.desc()).limit(5).all()
    observability.log_step("rca.search", f"records={len(results)}")
    return results
