"""Applicant accounts, invitations, guest chat and the independent clinic."""

import pytest

from ellis.db import Account, StaffUser, session_scope
from ellis.services import accounts
from ellis.services.accounts import AccountError


def test_create_account_and_independent_case(seeded):
    with session_scope() as s:
        acct = accounts.create_account(s, "Ana Pérez", "ana@x.test", "password1")
        case = accounts.create_independent_case(s, acct)
        assert case.clinic_id == "cl_independent"
        assert (case.first_name, case.last_name) == ("Ana", "Pérez")
        assert case.account_id == acct.id
        assert accounts.active_case(s, acct).id == case.id
        assert accounts.is_independent(case)
        assert [c.id for c in accounts.cases_for(s, acct)] == [case.id]


def test_email_unique_across_staff_and_accounts(seeded):
    with session_scope() as s:
        with pytest.raises(AccountError) as e:
            accounts.create_account(s, "Dana", "dana@valle.demo", "password1")
        assert e.value.status == 409
        accounts.create_account(s, "Ana", "Ana@X.test ", "password1")
        with pytest.raises(AccountError) as e:
            accounts.create_account(s, "Ana 2", "ana@x.test", "password1")
        assert e.value.status == 409


def test_weak_password_rejected(seeded):
    with session_scope() as s:
        with pytest.raises(AccountError) as e:
            accounts.create_account(s, "Ana", "ana@x.test", "short")
        assert e.value.code == "weak_password"
        with pytest.raises(AccountError) as e:
            accounts.create_account(s, "Ana", "nope", "password1")
        assert e.value.code == "bad_email"


def test_authenticate_both_kinds(seeded):
    with session_scope() as s:
        accounts.create_account(s, "Ana Pérez", "ana@x.test", "password1")
    with session_scope() as s:
        assert isinstance(accounts.authenticate(s, "ana@x.test", "password1"), Account)
        assert isinstance(accounts.authenticate(s, "dana@valle.demo", "ellis-demo"), StaffUser)
        assert accounts.authenticate(s, "ana@x.test", "wrong") is None
        assert accounts.authenticate(s, "nobody@x.test", "password1") is None
        s.query(StaffUser).filter_by(email="dana@valle.demo").one().active = False
        s.flush()
        assert accounts.authenticate(s, "dana@valle.demo", "ellis-demo") is None
