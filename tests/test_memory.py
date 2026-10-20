import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import db, memory


class DurableMemoryTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        db.Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)()
        tenant = db.Tenant(name="tenant")
        self.user = db.User(username="memory-user", hashed_password="test", tenant=tenant)
        other_user = db.User(username="other-user", hashed_password="test", tenant=tenant)
        self.session.add_all([self.user, other_user])
        self.session.commit()
        self.other_user = other_user
        self.tenant_id = tenant.id

    def tearDown(self):
        self.session.close()

    def test_history_is_ordered_and_scoped_to_owner(self):
        memory.add_exchange(
            self.session,
            session_id="conversation-1",
            request_id="request-1",
            user_id=self.user.id,
            tenant_id=self.tenant_id,
            question="first question",
            answer="first answer",
        )
        memory.add_exchange(
            self.session,
            session_id="conversation-1",
            request_id="request-2",
            user_id=self.user.id,
            tenant_id=self.tenant_id,
            question="second question",
            answer="second answer",
        )
        self.session.commit()

        self.assertEqual(
            memory.get_recent_messages(
                self.session, "conversation-1", self.user.id, self.tenant_id
            ),
            [
                {"role": "user", "content": "first question"},
                {"role": "assistant", "content": "first answer"},
                {"role": "user", "content": "second question"},
                {"role": "assistant", "content": "second answer"},
            ],
        )
        self.assertEqual(
            memory.get_recent_messages(
                self.session, "conversation-1", self.other_user.id, self.tenant_id
            ),
            [],
        )
        self.assertFalse(
            memory.session_belongs_to_user(
                self.session, "conversation-1", self.other_user.id, self.tenant_id
            )
        )

    def test_long_term_record_is_database_backed(self):
        record = memory.add_long_term_record(
            self.session,
            session_id="conversation-1",
            user_id=self.user.id,
            tenant_id=self.tenant_id,
            summary="A durable support memory",
        )
        self.session.commit()

        stored = self.session.get(db.LongTermMemoryRecord, record.id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.summary, "A durable support memory")


if __name__ == "__main__":
    unittest.main()
