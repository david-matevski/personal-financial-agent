"""Tests for finagent.domain.hashing."""

from datetime import date
from decimal import Decimal

from finagent.domain.hashing import assign_row_sequences, normalize_description, transaction_hash
from finagent.domain.models import AccountType, Issuer, Transaction


def _debit_tx(**overrides: object) -> Transaction:
    defaults: dict[str, object] = {
        "issuer": Issuer.TD,
        "account_type": AccountType.DEBIT,
        "account_label": "Chequing 1234",
        "posted_date": date(2024, 1, 15),
        "description": "COFFEE SHOP",
        "amount": Decimal("4.50"),
        "running_balance": Decimal("1000.00"),
    }
    defaults.update(overrides)
    return Transaction.model_validate(defaults)


def _credit_tx(**overrides: object) -> Transaction:
    defaults: dict[str, object] = {
        "issuer": Issuer.AMEX,
        "account_type": AccountType.CREDIT,
        "account_label": "Gold Card 1234",
        "posted_date": date(2024, 1, 15),
        "description": "COFFEE SHOP",
        "amount": Decimal("4.50"),
    }
    defaults.update(overrides)
    return Transaction.model_validate(defaults)


def test_normalize_description_collapses_whitespace_and_uppercases() -> None:
    assert normalize_description("  coffee   shop\t#42  ") == "COFFEE SHOP #42"


def test_transaction_hash_is_deterministic() -> None:
    tx = _debit_tx()
    assert transaction_hash(tx) == transaction_hash(tx)


def test_transaction_hash_is_64_char_hex() -> None:
    digest = transaction_hash(_debit_tx())
    assert len(digest) == 64
    int(digest, 16)  # raises ValueError if not valid hex


def test_transaction_hash_differs_for_different_descriptions() -> None:
    tx_a = _debit_tx(description="COFFEE SHOP")
    tx_b = _debit_tx(description="GROCERY STORE")
    assert transaction_hash(tx_a) != transaction_hash(tx_b)


def test_transaction_hash_normalizes_description_case_and_whitespace() -> None:
    tx_a = _debit_tx(description="Coffee   Shop")
    tx_b = _debit_tx(description="  COFFEE SHOP  ")
    assert transaction_hash(tx_a) == transaction_hash(tx_b)


def test_debit_hash_depends_on_running_balance() -> None:
    tx_a = _debit_tx(running_balance=Decimal("1000.00"))
    tx_b = _debit_tx(running_balance=Decimal("995.50"))
    assert transaction_hash(tx_a) != transaction_hash(tx_b)


def test_credit_hash_depends_on_account_label() -> None:
    # Two cards of the same issuer/type (e.g. two TD Visas) must not collide
    # even when date/description/amount/row_sequence are identical.
    tx_a = _credit_tx(account_label="Visa Infinite 1111")
    tx_b = _credit_tx(account_label="Visa Infinite 2222")
    assert transaction_hash(tx_a) != transaction_hash(tx_b)


def test_credit_hash_depends_on_row_sequence() -> None:
    tx_a = _credit_tx(row_sequence=0)
    tx_b = _credit_tx(row_sequence=1)
    assert transaction_hash(tx_a) != transaction_hash(tx_b)


def test_credit_hash_ignores_running_balance_field() -> None:
    # Credit transactions don't carry a meaningful running balance; the hash
    # must not depend on it (it keys on row_sequence instead).
    tx_a = _credit_tx(row_sequence=0, running_balance=None)
    tx_b = _credit_tx(row_sequence=0, running_balance=Decimal("50.00"))
    assert transaction_hash(tx_a) == transaction_hash(tx_b)


def test_debit_hash_ignores_row_sequence_field() -> None:
    tx_a = _debit_tx(row_sequence=0)
    tx_b = _debit_tx(row_sequence=1)
    assert transaction_hash(tx_a) == transaction_hash(tx_b)


def test_assign_row_sequences_numbers_duplicates_in_order() -> None:
    dup1 = _credit_tx(description="COFFEE SHOP", amount=Decimal("5.00"))
    dup2 = _credit_tx(description="COFFEE SHOP", amount=Decimal("5.00"))
    other = _credit_tx(description="GROCERY STORE", amount=Decimal("20.00"))

    result = assign_row_sequences([dup1, other, dup2])

    assert result[0].row_sequence == 0  # dup1
    assert result[1].row_sequence == 0  # other (distinct group)
    assert result[2].row_sequence == 1  # dup2


def test_assign_row_sequences_distinguishes_by_date_description_amount() -> None:
    tx_a = _credit_tx(posted_date=date(2024, 1, 15))
    tx_b = _credit_tx(posted_date=date(2024, 1, 16))

    result = assign_row_sequences([tx_a, tx_b])

    assert result[0].row_sequence == 0
    assert result[1].row_sequence == 0


def test_assign_row_sequences_preserves_other_fields() -> None:
    tx = _credit_tx(description="COFFEE SHOP")
    (result,) = assign_row_sequences([tx])
    assert result.description == tx.description
    assert result.amount == tx.amount
