import hashlib
from sqlalchemy.orm import Session

from app import auth, db


def hash_password(password: str) -> str:
    return auth.hash_password(password)


def ensure_default_data(db_session: Session) -> None:
    tenant = db_session.query(db.Tenant).filter(db.Tenant.name == "default").first()
    if tenant is None:
        tenant = db.Tenant(name="default", description="Default tenant")
        db_session.add(tenant)
        db_session.commit()
        db_session.refresh(tenant)

    role_specs = {
        "admin": ["query_support", "manage_rca", "submit_feedback"],
        "support": ["query_support", "submit_feedback"],
        "user": ["query_support", "submit_feedback"],
    }
    permission_map = {}
    for permission_name in {permission_name for names in role_specs.values() for permission_name in names}:
        permission = db_session.query(db.Permission).filter(db.Permission.name == permission_name).first()
        if permission is None:
            permission = db.Permission(name=permission_name, description=f"Permission: {permission_name}")
            db_session.add(permission)
            db_session.commit()
            db_session.refresh(permission)
        permission_map[permission_name] = permission

    roles = {}
    for role_name, permission_names in role_specs.items():
        role = db_session.query(db.Role).filter(db.Role.name == role_name).first()
        if role is None:
            role = db.Role(name=role_name, description=f"{role_name.title()} access")
            db_session.add(role)
            db_session.commit()
            db_session.refresh(role)
        role.permissions = [permission_map[name] for name in permission_names]
        roles[role_name] = role
        db_session.add(role)

    user_specs = {
        "admin": ("admin123", "admin"),
        "support": ("support123", "support"),
        "user": ("user123", "user"),
    }
    for username, (password, role_name) in user_specs.items():
        user = db_session.query(db.User).filter(db.User.username == username).first()
        if user is None:
            user = db.User(username=username, hashed_password=hash_password(password), tenant_id=tenant.id, is_active=True)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
        user.is_active = True
        user.tenant_id = tenant.id
        user.roles = [roles[role_name]]

    db_session.commit()


def seed_database(db_session: Session) -> None:
    ensure_default_data(db_session)
    print("Seed data created: admin/support/user")


if __name__ == "__main__":
    db.init_db()
    session = db.SessionLocal()
    try:
        seed_database(session)
    finally:
        session.close()
